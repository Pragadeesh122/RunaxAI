"""Pinecone index management and vector operations for project namespaces."""

import logging
import os
from observability.spans import retrieval_span

logger = logging.getLogger("pipeline.pinecone")

INDEX_NAME = "agenticrag"
DENSE_DIMENSION = int(os.getenv("DENSE_EMBEDDING_DIMENSION", 1536))
DENSE_METRIC = "dotproduct"  # required for hybrid search


def ensure_index() -> None:
    """Create the Pinecone index if it doesn't exist.

    Hard-fails if an existing index has a different dimension than the
    configured one — otherwise upserts would silently corrupt the namespace.
    """
    from clients import pinecone_client
    from pinecone import ServerlessSpec

    existing_indexes = list(pinecone_client.list_indexes())
    existing_names = [idx.name for idx in existing_indexes]
    if INDEX_NAME in existing_names:
        idx = next(i for i in existing_indexes if i.name == INDEX_NAME)
        current_dim = int(getattr(idx, "dimension"))
        if current_dim != DENSE_DIMENSION:
            raise ValueError(
                f"Pinecone index '{INDEX_NAME}' has dimension {current_dim} but "
                f"DENSE_EMBEDDING_DIMENSION is configured as {DENSE_DIMENSION}. "
                "Either set DENSE_EMBEDDING_DIMENSION to match the existing "
                "index, or delete the index and reingest all documents."
            )
        logger.info(f"index '{INDEX_NAME}' already exists (dim={current_dim})")
        return

    pinecone_client.create_index(
        name=INDEX_NAME,
        dimension=DENSE_DIMENSION,
        metric=DENSE_METRIC,
        spec=ServerlessSpec(cloud="aws", region="us-east-1"),
    )
    logger.info(f"created index '{INDEX_NAME}'")


def get_index():
    """Return a handle to the Pinecone index."""
    from clients import pinecone_client

    return pinecone_client.Index(INDEX_NAME)


def namespace_for_project(project_id: str) -> str:
    return f"project_{project_id}"


def upsert_vectors(
    project_id: str,
    vectors: list[dict],
    batch_size: int = 100,
) -> int:
    """Upsert vectors into the project's namespace.

    Each vector dict: {id, values, sparse_values, metadata}
    """
    index = get_index()
    ns = namespace_for_project(project_id)
    total = 0

    for i in range(0, len(vectors), batch_size):
        batch = vectors[i : i + batch_size]
        index.upsert(vectors=batch, namespace=ns)
        total += len(batch)
        logger.info(f"upserted batch {i // batch_size + 1} ({len(batch)} vectors)")

    logger.info(f"upserted {total} vectors to namespace '{ns}'")
    return total


def query_vectors(
    project_id: str,
    dense_vector: list[float],
    sparse_vector: dict | None = None,
    top_k: int = 5,
    alpha: float = 1.0,
) -> list[dict]:
    """Query the project namespace with optional hybrid weighting.

    alpha=1.0 → pure dense, alpha=0.0 → pure sparse
    """
    with retrieval_span(span_name="retrieval.vector_query") as span:
        index = get_index()
        ns = namespace_for_project(project_id)

        query_kwargs = {
            "namespace": ns,
            "top_k": top_k,
            "include_metadata": True,
        }

        if sparse_vector and alpha < 1.0:
            # Apply hybrid weighting
            query_kwargs["vector"] = [v * alpha for v in dense_vector]
            query_kwargs["sparse_vector"] = {
                "indices": sparse_vector["indices"],
                "values": [v * (1 - alpha) for v in sparse_vector["values"]],
            }
        else:
            query_kwargs["vector"] = dense_vector

        results = index.query(**query_kwargs)

        matches = [
            {
                "id": match.id,
                "score": match.score,
                "text": match.metadata.get("text", ""),
                "source": match.metadata.get("source", ""),
                "page": match.metadata.get("page"),
                "document_id": match.metadata.get("document_id", ""),
            }
            for match in results.matches
        ]
        if span is not None:
            span.set_attribute("vector.hits", len(matches))
        return matches


def delete_namespace(project_id: str) -> None:
    """Delete all vectors in a project's namespace."""
    index = get_index()
    ns = namespace_for_project(project_id)
    index.delete(delete_all=True, namespace=ns)
    logger.info(f"deleted namespace '{ns}'")


def delete_document_vectors(project_id: str, document_id: str) -> None:
    """Delete all vectors for a specific document within a project namespace."""
    index = get_index()
    ns = namespace_for_project(project_id)
    # Pinecone supports metadata filtering for delete
    index.delete(
        filter={"document_id": {"$eq": document_id}},
        namespace=ns,
    )
    logger.info(f"deleted vectors for document '{document_id}' in namespace '{ns}'")
