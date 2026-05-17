import logging
import os
from dotenv import load_dotenv
from clients import llm_client
from llm.response_utils import extract_first_embedding

load_dotenv()

logger = logging.getLogger("portfolio-agent")
EMBEDDING_MODEL = os.getenv("DENSE_EMBEDDING_MODEL", "text-embedding-3-large")

SCHEMA = {
    "type": "function",
    "function": {
        "name": "portfolio",
        "description": (
            "Search the Pragadeesh portfolio knowledge index for information about that person, their work, "
            "projects, or background. Use this for targeted portfolio lookups only. "
            "Do not use it for general web search or unrelated factual questions. "
            "Run one lookup first and only try a different formulation if the first result is insufficient. "
            "It returns a list of relevant portfolio passages with source information."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search about Pragadeesh",
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


def portfolio(query: str) -> list:
    try:
        embedding = llm_client.embeddings.create(
            input=query, model=EMBEDDING_MODEL
        )
        query_vector = extract_first_embedding(embedding)
    except Exception as e:
        logger.error(f"embedding failed: {e}")
        raise RuntimeError(f"Embedding failed: {e}") from e

    try:
        from clients import pinecone_client

        index = pinecone_client.Index("pragadeesh")
        results = index.query(vector=query_vector, top_k=5, include_metadata=True)
    except Exception as e:
        logger.error(f"pinecone query failed: {e}")
        raise RuntimeError(f"Pinecone query failed: {e}") from e

    cleaned_result = []
    for result in results["matches"]:
        metadata = result.get("metadata", {})
        cleaned_result.append(
            {"content": metadata.get("text"), "source": metadata.get("source")}
        )
    return cleaned_result
