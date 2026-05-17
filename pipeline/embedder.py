"""Dense + sparse embedding generation for hybrid search."""

import logging
import os
from clients import llm_client, pinecone_client
from llm.response_utils import extract_embedding_vectors

logger = logging.getLogger("pipeline.embedder")

DENSE_MODEL = os.getenv("DENSE_EMBEDDING_MODEL", "text-embedding-3-large")
# 1536d is the matryoshka-reduced dim for text-embedding-3-large — within
# ~1-2% of full 3072d on MTEB retrieval, at half the storage/QPS cost.
DENSE_DIMENSION = int(os.getenv("DENSE_EMBEDDING_DIMENSION", 1536))
SPARSE_MODEL = "pinecone-sparse-english-v0"

# Max texts per API call (Pinecone sparse limit is 96)
EMBEDDING_BATCH_SIZE = 96


def _supports_dimensions(model: str) -> bool:
    """Only text-embedding-3-* accepts the `dimensions` parameter."""
    return model.startswith("text-embedding-3")


def _dense_create(inputs):
    kwargs = {"input": inputs, "model": DENSE_MODEL}
    if _supports_dimensions(DENSE_MODEL):
        kwargs["dimensions"] = DENSE_DIMENSION
    return llm_client.embeddings.create(**kwargs)


def embed_dense(texts: list[str]) -> list[list[float]]:
    """Generate dense embeddings via the configured OpenAI model.

    Handles batching for large lists.
    """
    all_embeddings = []

    for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[i : i + EMBEDDING_BATCH_SIZE]
        response = _dense_create(batch)
        batch_embeddings = extract_embedding_vectors(response)
        all_embeddings.extend(batch_embeddings)
        logger.info(
            f"dense batch {i // EMBEDDING_BATCH_SIZE + 1}: "
            f"{len(batch)} texts embedded"
        )

    return all_embeddings


def embed_sparse(texts: list[str]) -> list[dict]:
    """Generate sparse embeddings via Pinecone's inference API.

    Returns list of {"indices": [...], "values": [...]}
    """
    all_sparse = []

    for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[i : i + EMBEDDING_BATCH_SIZE]
        response = pinecone_client.inference.embed(
            model=SPARSE_MODEL,
            inputs=batch,
            parameters={"input_type": "passage"},
        )
        for embedding in response.data:
            all_sparse.append({
                "indices": embedding.sparse_indices,
                "values": embedding.sparse_values,
            })
        logger.info(
            f"sparse batch {i // EMBEDDING_BATCH_SIZE + 1}: "
            f"{len(batch)} texts embedded"
        )

    return all_sparse


def embed_query_dense(query: str) -> list[float]:
    """Embed a single query string with the dense model."""
    response = _dense_create(query)
    return extract_embedding_vectors(response)[0]


def embed_query_sparse(query: str) -> dict:
    """Embed a single query string with the sparse model."""
    response = pinecone_client.inference.embed(
        model=SPARSE_MODEL,
        inputs=[query],
        parameters={"input_type": "query"},
    )
    embedding = response.data[0]
    return {
        "indices": embedding.sparse_indices,
        "values": embedding.sparse_values,
    }
