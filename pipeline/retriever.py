"""Adaptive retrieval layer with hybrid search support."""

import logging
from pipeline.embedder import embed_query_dense, embed_query_sparse
from pipeline.pinecone_helpers import query_vectors
from pipeline.retrieval_cache import get_cached_retrieval, cache_retrieval
from observability.spans import retrieval_span

logger = logging.getLogger("pipeline.retriever")


def get_retrieval_config(chunk_count: int) -> dict:
    """Select retrieval strategy based on corpus size.

    - Small (< 500 chunks): dense only, semantic is enough
    - Medium (500-10K): hybrid, BM25 helps with exact matches
    - Large (> 10K): hybrid + rerank candidates
    """
    if chunk_count < 500:
        return {"alpha": 1.0, "top_k": 5, "rerank": False}
    elif chunk_count < 10000:
        return {"alpha": 0.7, "top_k": 10, "rerank": False}
    else:
        return {"alpha": 0.5, "top_k": 20, "rerank": True}


def retrieve(
    project_id: str,
    query: str,
    chunk_count: int = 0,
    top_k: int | None = None,
    alpha: float | None = None,
) -> tuple[list[dict], dict]:
    """Retrieve relevant chunks from a project's vector store.

    Args:
        project_id: the project namespace in Pinecone
        query: the user's query
        chunk_count: total chunks in the project (for adaptive config)
        top_k: override for number of results
        alpha: override for dense/sparse weighting (1.0=dense, 0.0=sparse)

    Returns:
        Tuple of (results, info) where:
          - results: list of {"id", "score", "text", "source", "page", "document_id"}
          - info: {"cache_hit": bool} — whether results came from the semantic cache
    """
    with retrieval_span(
        span_name="retrieval.pipeline",
        **{"retrieval.top_k": top_k, "retrieval.alpha": alpha},
    ) as span:
        # Check retrieval cache first (cache module logs the hit/miss itself)
        cached = get_cached_retrieval(project_id, query)
        if cached is not None:
            if span is not None:
                span.set_attribute("cache.hit", True)
                span.set_attribute("result_count", len(cached))
            return cached, {"cache_hit": True}

        config = get_retrieval_config(chunk_count)

        if top_k is not None:
            config["top_k"] = top_k
        if alpha is not None:
            config["alpha"] = alpha

        if span is not None:
            span.set_attribute("cache.hit", False)
            span.set_attribute("retrieval.mode", "hybrid" if config["alpha"] < 1.0 else "dense")
            span.set_attribute("retrieval.top_k", config["top_k"])
            span.set_attribute("retrieval.alpha", config["alpha"])
            span.set_attribute("retrieval.rerank", config["rerank"])

        logger.info(
            f"retrieving from project '{project_id}' | "
            f"alpha={config['alpha']}, top_k={config['top_k']}, "
            f"rerank={config['rerank']}"
        )

        # Generate embeddings
        dense_vec = embed_query_dense(query)

        sparse_vec = None
        if config["alpha"] < 1.0:
            sparse_vec = embed_query_sparse(query)

        # Query Pinecone
        results = query_vectors(
            project_id=project_id,
            dense_vector=dense_vec,
            sparse_vector=sparse_vec,
            top_k=config["top_k"],
            alpha=config["alpha"],
        )

        # If reranking is enabled, take more results and rerank
        if config["rerank"] and len(results) > 10:
            with retrieval_span(span_name="retrieval.rerank"):
                results = _rerank(query, results, final_k=10)

        # Cache the results
        if results:
            cache_retrieval(project_id, query, results)

        if span is not None:
            span.set_attribute("result_count", len(results))

        logger.info(f"retrieved {len(results)} results")
        return results, {"cache_hit": False}


def _rerank(query: str, results: list[dict], final_k: int = 10) -> list[dict]:
    """Rerank results using Pinecone's reranker.

    Falls back to score-based ordering if reranker is unavailable.
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
        logger.warning(f"reranking failed, using score order: {e}")
        return sorted(results, key=lambda r: r["score"], reverse=True)[:final_k]
