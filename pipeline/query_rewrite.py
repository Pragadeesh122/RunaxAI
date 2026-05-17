"""Query rewriting for retrieval — currently HyDE (Hypothetical Document Embeddings).

HyDE generates a synthetic answer to the user's query and embeds *that*
instead of the raw query. The synthetic passage shares more vocabulary and
phrasing with relevant source documents, which often improves recall —
especially for short or under-specified queries.
"""

import logging

from clients import llm_client
from llm.response_utils import extract_first_text

logger = logging.getLogger("pipeline.query_rewrite")

HYDE_SYSTEM_PROMPT = (
    "You write short hypothetical passages that would answer the user's question, "
    "for the purpose of semantic search.\n\n"
    "Rules:\n"
    "- Write 2-4 sentences that read like an excerpt from a document that directly answers the question.\n"
    "- Use domain-specific terminology and concrete details. Do NOT hedge with phrases like 'it depends' or 'generally'.\n"
    "- Do NOT include preamble, restate the question, or use bullet points.\n"
    "- If the question is ambiguous, pick the most likely interpretation and commit to it.\n"
    "- Output the passage only — no quotes, no formatting."
)


def generate_hyde_passage(query: str) -> str:
    """Return a hypothetical answer passage to use as a retrieval query.

    Falls back to the original query string on any failure so the caller
    can ignore the failure mode.
    """
    try:
        response = llm_client.chat.completions.create(
            messages=[
                {"role": "system", "content": HYDE_SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            temperature=0.3,
            max_tokens=200,
        )
        passage = extract_first_text(response, "").strip()
        if not passage:
            return query
        # Keep the original query in there too — helps when the LLM
        # over-specializes the hypothetical passage away from the intent.
        return f"{query}\n\n{passage}"
    except Exception as e:
        logger.warning(f"HyDE generation failed, using raw query: {e}")
        return query
