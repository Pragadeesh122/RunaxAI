"""Adaptive retrieval layer with hybrid search and cross-encoder reranking."""

import logging
import os
import random
import threading

from pipeline.embedder import embed_query_dense, embed_query_sparse
from pipeline.pinecone_helpers import query_vectors
from pipeline.query_rewrite import generate_hyde_passage
from pipeline.retrieval_cache import get_cached_retrieval, cache_retrieval
from observability.spans import retrieval_span

logger = logging.getLogger("pipeline.retriever")

# How many extra candidates to fetch before reranking. final = top_k,
# pre-rerank pool = top_k * RERANK_OVERSAMPLE (capped at RERANK_MAX_POOL).
RERANK_OVERSAMPLE = 4
RERANK_MAX_POOL = 60

# Fraction of cache hits to shadow-validate against a fresh retrieval.
# Default off; set to e.g. 0.05 to audit 5% of hits.
CACHE_AUDIT_RATE = float(os.getenv("RETRIEVAL_CACHE_AUDIT_RATE", "0"))


def get_retrieval_config(chunk_count: int) -> dict:
    """Select retrieval strategy based on corpus size.

    Reranking always runs — small corpora benefit from it as much as large
    ones, and the latency cost is ~100-300ms. What changes by tier is the
    hybrid alpha (more sparse weight on larger corpora, where lexical
    matches matter more) and the final top_k.
    """
    if chunk_count < 500:
        return {"alpha": 1.0, "top_k": 5, "rerank": True}
    elif chunk_count < 10000:
        return {"alpha": 0.7, "top_k": 10, "rerank": True}
    else:
        return {"alpha": 0.5, "top_k": 20, "rerank": True}


def retrieve(
    project_id: str,
    query: str,
    chunk_count: int = 0,
    top_k: int | None = None,
    alpha: float | None = None,
    use_hyde: bool = False,
) -> tuple[list[dict], dict]:
    """Retrieve relevant chunks from a project's vector store.

    Args:
        project_id: the project namespace in Pinecone
        query: the user's query
        chunk_count: total chunks in the project (for adaptive config)
        top_k: override for number of results
        alpha: override for dense/sparse weighting (1.0=dense, 0.0=sparse)
        use_hyde: rewrite the query as a hypothetical answer passage
            before embedding. Helps short/vague queries match better.

    Returns:
        Tuple of (results, info) where:
          - results: list of {"id", "score", "text", "source", "page", "document_id"}
          - info: {"cache_hit": bool} — whether results came from the semantic cache
    """
    with retrieval_span(
        span_name="retrieval.pipeline",
        **{"retrieval.top_k": top_k, "retrieval.alpha": alpha},
    ) as span:
        # Cache lookup uses the raw user query — HyDE rewrites change every
        # call (temperature > 0), so caching against the rewrite would
        # destroy hit rates.
        cached = get_cached_retrieval(project_id, query)
        if cached is not None:
            if span is not None:
                span.set_attribute("cache.hit", True)
                span.set_attribute("result_count", len(cached))
            if CACHE_AUDIT_RATE > 0 and random.random() < CACHE_AUDIT_RATE:
                _schedule_cache_audit(
                    project_id, query, cached, chunk_count, top_k, alpha, use_hyde
                )
            return cached, {"cache_hit": True}

        config = get_retrieval_config(chunk_count)
        if top_k is not None:
            config["top_k"] = top_k
        if alpha is not None:
            config["alpha"] = alpha

        results = _retrieve_uncached(query, project_id, config, use_hyde, span)

        if results:
            cache_retrieval(project_id, query, results)

        if span is not None:
            span.set_attribute("result_count", len(results))

        logger.info(f"retrieved {len(results)} results")
        return results, {"cache_hit": False}


def _retrieve_uncached(
    query: str,
    project_id: str,
    config: dict,
    use_hyde: bool,
    span,
) -> list[dict]:
    """Run the full retrieval pipeline (HyDE → embed → query → rerank)."""
    if span is not None:
        span.set_attribute("cache.hit", False)
        span.set_attribute("retrieval.mode", "hybrid" if config["alpha"] < 1.0 else "dense")
        span.set_attribute("retrieval.top_k", config["top_k"])
        span.set_attribute("retrieval.alpha", config["alpha"])
        span.set_attribute("retrieval.rerank", config["rerank"])
        span.set_attribute("retrieval.hyde", use_hyde)

    logger.info(
        f"retrieving from project '{project_id}' | "
        f"alpha={config['alpha']}, top_k={config['top_k']}, "
        f"rerank={config['rerank']}, hyde={use_hyde}"
    )

    embed_text = query
    if use_hyde:
        with retrieval_span(span_name="retrieval.hyde"):
            embed_text = generate_hyde_passage(query)

    dense_vec = embed_query_dense(embed_text)
    sparse_vec = None
    if config["alpha"] < 1.0:
        # Sparse stays on the literal query — HyDE passages dilute the
        # exact keyword signal that's the whole point of sparse retrieval.
        sparse_vec = embed_query_sparse(query)

    pool_size = (
        min(config["top_k"] * RERANK_OVERSAMPLE, RERANK_MAX_POOL)
        if config["rerank"]
        else config["top_k"]
    )

    results = query_vectors(
        project_id=project_id,
        dense_vector=dense_vec,
        sparse_vector=sparse_vec,
        top_k=pool_size,
        alpha=config["alpha"],
    )

    if config["rerank"] and len(results) > config["top_k"]:
        with retrieval_span(span_name="retrieval.rerank"):
            # Rerank against the literal query, not the HyDE passage —
            # the reranker scores query↔doc relevance, and the literal
            # query is what we actually want answered.
            results = _rerank(query, results, final_k=config["top_k"])

    return results


def _rerank(query: str, results: list[dict], final_k: int) -> list[dict]:
    """Rerank results using Pinecone's hosted bge-reranker-v2-m3.

    Falls back to score-based ordering if reranking fails — logged loudly
    so a silently degraded reranker is noticed.
    """
    try:
        from clients import pinecone_client

        documents = [r["text"] for r in results]
        reranked = pinecone_client.inference.rerank(
            model="bge-reranker-v2-m3",
            query=query,
            documents=documents,
            top_n=final_k,
        )

        reranked_results = []
        for item in reranked.data:
            original = results[item.index]
            original["score"] = item.score
            reranked_results.append(original)

        logger.info(f"reranked {len(results)} → {len(reranked_results)} results")
        return reranked_results

    except Exception as e:
        logger.error(
            f"RERANK FAILED — falling back to vector scores. err={e}",
            exc_info=True,
        )
        return sorted(results, key=lambda r: r["score"], reverse=True)[:final_k]


def _schedule_cache_audit(
    project_id: str,
    query: str,
    cached: list[dict],
    chunk_count: int,
    top_k: int | None,
    alpha: float | None,
    use_hyde: bool,
) -> None:
    """Fire-and-forget shadow retrieval to measure cache precision.

    Runs in a daemon thread so it doesn't block the user response. The
    purpose is offline analysis — look at the logs to see whether cache
    hits actually return the same chunks a fresh retrieval would have.
    """
    def _run():
        try:
            config = get_retrieval_config(chunk_count)
            if top_k is not None:
                config["top_k"] = top_k
            if alpha is not None:
                config["alpha"] = alpha

            fresh = _retrieve_uncached(query, project_id, config, use_hyde, span=None)
            cached_ids = {r["id"] for r in cached}
            fresh_ids = {r["id"] for r in fresh}
            overlap = cached_ids & fresh_ids
            denom = max(len(cached_ids), 1)
            logger.info(
                f"cache audit project={project_id} overlap={len(overlap)}/{denom} "
                f"cached_top1={next(iter(cached), {}).get('id')} "
                f"fresh_top1={next(iter(fresh), {}).get('id')} "
                f"query='{query[:80]}'"
            )
        except Exception as e:
            logger.warning(f"cache audit failed: {e}")

    threading.Thread(target=_run, daemon=True).start()
