import requests
import os
import logging
from clients import llm_client
from prompts.search_summarizer import SEARCH_SUMMARIZER
from llm.response_utils import extract_first_text, usage_tokens

logger = logging.getLogger("search-agent")

SCHEMA = {
    "type": "function",
    "function": {
        "name": "search",
        "description": (
            "Search the public web for current or external information. "
            "Use this for up-to-date facts, news, dates, prices, or multiple independent lookups. "
            "Do not use it when you already have one exact page URL to inspect; use crawl_website instead. "
            "This tool is safe for parallel fan-out across distinct queries. "
            "It returns a concise text summary of the top search findings."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to look up on the web",
                },
            },
            "required": ["query"],
        },
    },
}

CACHEABLE = True
POLICY = {
    "execution_mode": "parallel_safe",
    "max_parallel_instances": 3,
    "requires_fresh_input": False,
    "dedupe_key_fields": ("query",),
    "verification_only_after_result": False,
}


def search(query: str) -> str:
    api_key = os.getenv("BRAVE_API_KEY")
    if not api_key:
        logger.error("BRAVE_API_KEY not set")
        raise RuntimeError("Search unavailable: BRAVE_API_KEY not configured")

    try:
        response = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": api_key},
            params={"q": query, "count": 5, "extra_snippets": True},
            timeout=10,
        )
        response.raise_for_status()
    except requests.Timeout as e:
        logger.error(f"brave search timed out for: '{query}'")
        raise RuntimeError("Search timed out") from e
    except requests.RequestException as e:
        logger.error(f"brave search request failed: {e}")
        raise RuntimeError(f"Search request failed: {e}") from e

    searchResponse = response.json().get("web", {}).get("results", [])

    results = []
    for result in searchResponse:
        results.append(
            {
                "title": result["title"],
                "url": result["url"],
                "description": result.get("description", ""),
                "extra_snippets": result.get("extra_snippets", []),
            }
        )

    logger.info(f"brave-search results={len(results)} query='{query[:80]}'")

    if not results:
        return f"No search results found for: '{query}'"

    try:
        llm_response = llm_client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": SEARCH_SUMMARIZER,
                },
                {"role": "user", "content": str(results)},
            ],
        )
        prompt_tokens, completion_tokens = usage_tokens(
            getattr(llm_response, "usage", None) or {}
        )

        logger.info(
            f"llm  call=search-summarize tokens_in={prompt_tokens} tokens_out={completion_tokens}"
        )
        return extract_first_text(llm_response, "")
    except Exception as e:
        logger.error(f"summarization failed: {e}")
        return str(results)
