"""RAG evaluation runner.

Usage:
    uv run python evals/run_eval.py --dataset smoke [--skip-judge] [--judge-model gpt-4o-mini]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from evals.metrics import recall_at_k, mrr, ndcg_at_k, substring_recall
from evals.judge import judge_answer

logger = logging.getLogger("evals.runner")

EVALS_DIR = Path(__file__).resolve().parent
REPORTS_DIR = EVALS_DIR / "reports"


def load_config() -> dict:
    config_path = EVALS_DIR / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_queries(dataset: str) -> list[dict]:
    queries_path = EVALS_DIR / "datasets" / dataset / "queries.jsonl"
    queries = []
    with open(queries_path) as f:
        for line in f:
            line = line.strip()
            if line:
                queries.append(json.loads(line))
    return queries


def get_document_paths(dataset: str) -> list[Path]:
    docs_dir = EVALS_DIR / "datasets" / dataset / "documents"
    return sorted(docs_dir.glob("*"))


def _create_eval_project(run_id: str) -> tuple[str, any]:
    """Create an ephemeral project for this eval run via SQLAlchemy.

    Returns (project_id, engine) for cleanup.
    """
    from sqlalchemy import create_engine, text
    from database.core import DATABASE_URL

    engine = create_engine(DATABASE_URL.replace("+asyncpg", "+psycopg2"))
    project_id = f"eval-{run_id}"

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO projects (id, name, description, status, user_id) "
                "VALUES (:id, :name, :desc, :status, :user_id)"
            ),
            {
                "id": project_id,
                "name": f"eval-{run_id}",
                "desc": "Ephemeral eval project",
                "status": "active",
                "user_id": "eval-system",
            },
        )
    return project_id, engine


def _ingest_documents(
    project_id: str,
    doc_paths: list[Path],
    config: dict,
) -> int:
    """Ingest eval documents and return total chunk count."""
    from pipeline.ingestion import ingest_document
    from pipeline.storage import ensure_bucket, BUCKET_NAME
    from clients import minio_client

    ensure_bucket()
    total_chunks = 0

    for doc_path in doc_paths:
        doc_id = str(uuid.uuid4())
        ext = doc_path.suffix.lstrip(".")
        object_key = f"{project_id}/{doc_id}.{ext}"

        minio_client.fput_object(BUCKET_NAME, object_key, str(doc_path))

        result = ingest_document(
            object_key=object_key,
            project_id=project_id,
            document_id=doc_id,
            filename=doc_path.name,
            chunk_size=config.get("ingestion", {}).get("chunk_size", 2000),
            chunk_overlap=config.get("ingestion", {}).get("chunk_overlap", 300),
        )
        total_chunks += result["chunk_count"]
        logger.info(
            f"ingested {doc_path.name}: {result['chunk_count']} chunks "
            f"({result['chunk_strategy']})"
        )

    return total_chunks


def _wait_for_pinecone_consistency(project_id: str, expected_chunks: int, config: dict):
    """Poll Pinecone index stats until vectors are queryable."""
    from pipeline.pinecone_helpers import get_index, namespace_for_project

    ns = namespace_for_project(project_id)
    poll_interval = config.get("run", {}).get("poll_interval", 2)
    max_wait = config.get("run", {}).get("max_poll_wait", 60)
    start = time.time()

    while time.time() - start < max_wait:
        try:
            stats = get_index().describe_index_stats()
            ns_stats = stats.get("namespaces", {}).get(ns, {})
            count = ns_stats.get("vector_count", 0)
            if count >= expected_chunks:
                logger.info(f"Pinecone consistent: {count}/{expected_chunks} vectors")
                return
        except Exception as e:
            logger.warning(f"index stats poll failed: {e}")
        time.sleep(poll_interval)

    logger.warning(
        f"Pinecone consistency timeout after {max_wait}s — proceeding anyway"
    )


def _run_retrieval_eval(
    project_id: str,
    queries: list[dict],
    chunk_count: int,
    config: dict,
) -> list[dict]:
    """Run retrieval for each query and compute metrics."""
    from pipeline.retriever import retrieve

    k_values = config.get("retrieval_metrics", {}).get("k_values", [5, 10, 20])
    max_k = max(k_values)
    results = []

    for q in queries:
        try:
            retrieved, _ = retrieve(
                project_id=project_id,
                query=q["query"],
                chunk_count=chunk_count,
                top_k=max_k,
            )
        except Exception as e:
            logger.error(f"retrieval failed for {q['id']}: {e}")
            retrieved = []

        filenames = [r.get("source", "") for r in retrieved]
        texts = [r.get("text", "") for r in retrieved]
        expected_files = set(q.get("expected_doc_filenames", []))
        expected_subs = q.get("expected_chunk_substrings", [])

        metrics = {}
        for k in k_values:
            metrics[f"recall@{k}"] = recall_at_k(filenames, expected_files, k)
            metrics[f"ndcg@{k}"] = ndcg_at_k(filenames, expected_files, k)
        metrics["mrr"] = mrr(filenames, expected_files)
        metrics["substring_recall"] = substring_recall(texts, expected_subs)

        results.append({
            "query_id": q["id"],
            "query": q["query"],
            "retrieved_filenames": filenames[:max_k],
            "retrieved_texts": texts[:max_k],
            "metrics": metrics,
        })

    return results


def _run_judge_eval(
    queries: list[dict],
    retrieval_results: list[dict],
    llm_client,
    config: dict,
) -> list[dict]:
    """Run end-to-end answer generation + judge scoring for each query."""
    from api.session import create_session, delete_session
    from api.project_chat import project_chat_stream

    judge_model = config.get("judge", {}).get("model", "gpt-4o-mini")
    judge_results = []

    for q, ret in zip(queries, retrieval_results):
        # Generate an answer via project_chat_stream
        session_id = create_session("eval-user")
        try:
            events = list(project_chat_stream(
                session_id=session_id,
                user_message=q["query"],
                project_id=ret.get("_project_id", ""),
                chunk_count=ret.get("_chunk_count", 0),
            ))
            # Extract the full answer from token events
            answer_parts = []
            for event in events:
                if event.startswith("event: token\n"):
                    # SSE format: event: token\ndata: <text>\n\n
                    for line in event.split("\n"):
                        if line.startswith("data: "):
                            answer_parts.append(line[6:])
            answer = "".join(answer_parts)
        except Exception as e:
            logger.error(f"answer generation failed for {q['id']}: {e}")
            answer = ""
        finally:
            try:
                delete_session(session_id)
            except Exception:
                pass

        # Judge the answer
        scores = judge_answer(
            query=q["query"],
            answer=answer,
            retrieved_chunks=ret.get("retrieved_texts", [])[:5],
            expected_traits=q.get("expected_answer_traits", {}),
            llm_client=llm_client,
            model=judge_model,
        )

        judge_results.append({
            "query_id": q["id"],
            "answer": answer[:500],  # truncate for report
            "scores": scores,
        })

    return judge_results


def _aggregate_metrics(
    retrieval_results: list[dict],
    judge_results: list[dict] | None,
    config: dict,
) -> dict:
    """Compute aggregate statistics."""
    k_values = config.get("retrieval_metrics", {}).get("k_values", [5, 10, 20])
    n = len(retrieval_results)
    if n == 0:
        return {}

    agg = {}

    # Retrieval metrics
    for k in k_values:
        key = f"recall@{k}"
        values = [r["metrics"].get(key, 0) for r in retrieval_results]
        agg[key] = {"mean": sum(values) / n, "min": min(values), "max": max(values)}

        ndcg_key = f"ndcg@{k}"
        ndcg_values = [r["metrics"].get(ndcg_key, 0) for r in retrieval_results]
        agg[ndcg_key] = {"mean": sum(ndcg_values) / n, "min": min(ndcg_values), "max": max(ndcg_values)}

    mrr_values = [r["metrics"].get("mrr", 0) for r in retrieval_results]
    agg["mrr"] = {"mean": sum(mrr_values) / n, "min": min(mrr_values), "max": max(mrr_values)}

    sub_values = [r["metrics"].get("substring_recall", 0) for r in retrieval_results]
    agg["substring_recall"] = {"mean": sum(sub_values) / n, "min": min(sub_values), "max": max(sub_values)}

    # Judge metrics
    if judge_results:
        for dim in ["faithfulness", "completeness", "hallucination", "format_adherence"]:
            scores = [
                jr["scores"].get(dim, {}).get("score", 0)
                for jr in judge_results
            ]
            agg[f"judge_{dim}"] = {
                "mean": sum(scores) / len(scores),
                "min": min(scores),
                "max": max(scores),
            }

    return agg


def _generate_markdown_report(
    run_id: str,
    dataset: str,
    retrieval_results: list[dict],
    judge_results: list[dict] | None,
    aggregates: dict,
) -> str:
    """Generate a human-readable markdown report."""
    lines = [
        f"# RAG Evaluation Report",
        f"",
        f"- **Run ID:** {run_id}",
        f"- **Dataset:** {dataset}",
        f"- **Timestamp:** {datetime.now(timezone.utc).isoformat()}",
        f"- **Queries:** {len(retrieval_results)}",
        f"",
        f"## Aggregate Metrics",
        f"",
        f"| Metric | Mean | Min | Max |",
        f"|--------|------|-----|-----|",
    ]

    for metric, values in aggregates.items():
        lines.append(
            f"| {metric} | {values['mean']:.3f} | {values['min']:.3f} | {values['max']:.3f} |"
        )

    lines.extend(["", "## Per-Query Results", ""])

    for i, ret in enumerate(retrieval_results):
        lines.append(f"### {ret['query_id']}: {ret['query']}")
        lines.append("")
        lines.append(f"**Retrieved files:** {', '.join(ret['retrieved_filenames'][:5]) or '(none)'}")
        lines.append("")

        for k, v in ret["metrics"].items():
            lines.append(f"- {k}: {v:.3f}")

        if judge_results and i < len(judge_results):
            jr = judge_results[i]
            lines.append("")
            lines.append(f"**Answer (truncated):** {jr['answer'][:200]}...")
            lines.append("")
            for dim, score_info in jr["scores"].items():
                score = score_info.get("score", 0)
                reason = score_info.get("reason", "")
                lines.append(f"- {dim}: {score}/5 — {reason}")

        lines.append("")

    return "\n".join(lines)


def _cleanup(project_id: str, engine, doc_paths: list[Path]):
    """Delete Pinecone namespace, DB rows, and MinIO objects."""
    errors = []

    # 1. Delete Pinecone namespace
    try:
        from pipeline.pinecone_helpers import delete_namespace
        delete_namespace(project_id)
        logger.info(f"deleted Pinecone namespace for {project_id}")
    except Exception as e:
        errors.append(f"Pinecone cleanup: {e}")

    # 2. Delete DB rows
    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM documents WHERE project_id = :pid"),
                {"pid": project_id},
            )
            conn.execute(
                text("DELETE FROM projects WHERE id = :pid"),
                {"pid": project_id},
            )
        logger.info(f"deleted DB rows for {project_id}")
    except Exception as e:
        errors.append(f"DB cleanup: {e}")

    # 3. Delete MinIO objects
    try:
        from pipeline.storage import delete_project_objects
        delete_project_objects(project_id)
        logger.info(f"deleted MinIO objects for {project_id}")
    except Exception as e:
        errors.append(f"MinIO cleanup: {e}")

    if errors:
        for err in errors:
            logger.error(f"CLEANUP FAILURE: {err}")


def main():
    parser = argparse.ArgumentParser(description="Run RAG evaluation")
    parser.add_argument("--dataset", default="smoke", help="Dataset name under evals/datasets/")
    parser.add_argument("--skip-judge", action="store_true", help="Skip LLM judge evaluation")
    parser.add_argument("--judge-model", default=None, help="Override judge model")
    parser.add_argument("--retrieval-only", action="store_true", help="Only run retrieval metrics")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    config = load_config()

    if args.judge_model:
        config.setdefault("judge", {})["model"] = args.judge_model

    queries = load_queries(args.dataset)
    doc_paths = get_document_paths(args.dataset)
    logger.info(f"loaded {len(queries)} queries, {len(doc_paths)} documents from '{args.dataset}'")

    project_id = None
    engine = None

    try:
        # 1. Create ephemeral project
        project_id, engine = _create_eval_project(run_id)
        logger.info(f"created eval project: {project_id}")

        # 2. Ingest documents
        total_chunks = _ingest_documents(project_id, doc_paths, config)
        logger.info(f"ingested {total_chunks} total chunks")

        # 3. Wait for consistency
        _wait_for_pinecone_consistency(project_id, total_chunks, config)

        # 4. Run retrieval eval
        retrieval_results = _run_retrieval_eval(project_id, queries, total_chunks, config)

        # Attach project context for judge phase
        for ret in retrieval_results:
            ret["_project_id"] = project_id
            ret["_chunk_count"] = total_chunks

        # 5. Run judge eval (unless skipped)
        judge_results = None
        if not args.skip_judge and not args.retrieval_only:
            try:
                from clients import llm_client
                judge_results = _run_judge_eval(queries, retrieval_results, llm_client, config)
            except Exception as e:
                logger.error(f"judge eval failed: {e}")

        # 6. Aggregate
        aggregates = _aggregate_metrics(retrieval_results, judge_results, config)

        # 7. Write reports
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        # Strip internal keys before saving
        clean_retrieval = [
            {k: v for k, v in r.items() if not k.startswith("_")}
            for r in retrieval_results
        ]

        json_report = {
            "run_id": run_id,
            "dataset": args.dataset,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "queries": len(queries),
            "documents": len(doc_paths),
            "total_chunks": total_chunks,
            "aggregates": aggregates,
            "retrieval_results": clean_retrieval,
            "judge_results": judge_results,
        }

        json_path = REPORTS_DIR / f"{run_id}.json"
        with open(json_path, "w") as f:
            json.dump(json_report, f, indent=2)
        logger.info(f"wrote JSON report: {json_path}")

        md_report = _generate_markdown_report(
            run_id, args.dataset, clean_retrieval, judge_results, aggregates
        )
        md_path = REPORTS_DIR / f"{run_id}.md"
        with open(md_path, "w") as f:
            f.write(md_report)
        logger.info(f"wrote markdown report: {md_path}")

        # Print summary
        print(f"\n{'='*60}")
        print(f"Eval run {run_id} complete")
        print(f"{'='*60}")
        for metric, values in aggregates.items():
            print(f"  {metric}: {values['mean']:.3f} (min={values['min']:.3f}, max={values['max']:.3f})")
        print(f"\nReports: {json_path}")
        print(f"         {md_path}")

    finally:
        if project_id and engine:
            _cleanup(project_id, engine, doc_paths)


if __name__ == "__main__":
    main()
