import os
import json
import logging
import faiss
import numpy as np
from clients import llm_client
from llm.response_utils import extract_embedding_vectors, extract_first_embedding

logger = logging.getLogger("local-kb-agent")

INDEX_PATH = "data/faiss.index"
METADATA_PATH = "data/metadata.json"
EMBEDDING_MODEL = os.getenv("DENSE_EMBEDDING_MODEL", "text-embedding-3-large")

SCHEMA = {
    "type": "function",
    "function": {
        "name": "query_local_kb",
        "description": (
            "Search the local knowledge base for information about Citro Essential Oils Distillery Industry, "
            "essential oils, related products, processes, or company data. Use this for targeted knowledge-base lookups. "
            "Do not use it for live web facts or exact webpage extraction. "
            "Run one lookup first and only reformulate after seeing the result. "
            "It returns a list of relevant snippets with source and similarity score."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The query to search the local knowledge base",
                },
            },
            "required": ["query"],
        },
    },
}

CACHEABLE = True
POLICY = {
    "execution_mode": "sequential_first",
    "max_parallel_instances": 1,
    "requires_fresh_input": True,
    "dedupe_key_fields": ("query",),
    "verification_only_after_result": True,
}


def build_index(documents: list[dict]):
    """
    Build a FAISS index from documents.
    Each document should be: {"text": "...", "source": "..."}
    """
    texts = [doc["text"] for doc in documents]

    response = llm_client.embeddings.create(input=texts, model=EMBEDDING_MODEL)
    embeddings = np.array(extract_embedding_vectors(response), dtype=np.float32)

    dimension = int(embeddings.shape[1])
    index = faiss.IndexFlatL2(dimension)
    index.add(embeddings)

    faiss.write_index(index, INDEX_PATH)
    with open(METADATA_PATH, "w") as f:
        json.dump({"dimension": dimension, "documents": documents}, f, indent=2)

    logger.info(f"built index with {len(documents)} documents")


def query_local_kb(query: str) -> list:
    if not os.path.exists(INDEX_PATH):
        raise RuntimeError(
            "No local knowledge base found. Please build the index first."
        )

    try:
        index = faiss.read_index(INDEX_PATH)
        with open(METADATA_PATH, "r") as f:
            metadata = json.load(f)
            if isinstance(metadata, list):
                documents = metadata
            else:
                documents = metadata.get("documents", [])
    except Exception as e:
        logger.error(f"failed to load index/metadata: {e}")
        raise RuntimeError(f"Failed to load knowledge base: {e}") from e

    try:
        response = llm_client.embeddings.create(input=query, model=EMBEDDING_MODEL)
        query_vector = np.array([extract_first_embedding(response)], dtype=np.float32)
        if index.d != query_vector.shape[1]:
            raise RuntimeError(
                f"Embedding dimension mismatch: index={index.d}, "
                f"query={query_vector.shape[1]}. "
                "Rebuild the local index for the active embedding model."
            )
    except RuntimeError:
        raise
    except Exception as e:
        logger.error(f"embedding failed: {e}")
        raise RuntimeError(f"Embedding failed: {e}") from e

    distances, indices = index.search(query_vector, k=5)

    results = []
    for i, idx in enumerate(indices[0]):
        if idx < len(documents):
            results.append(
                {
                    "text": documents[idx]["text"],
                    "source": documents[idx].get("source", "unknown"),
                    "score": float(distances[0][i]),
                }
            )

    logger.info(f"query: '{query}' → {len(results)} results")

    return results
