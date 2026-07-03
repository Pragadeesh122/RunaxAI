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


def _tavily_search(query: str, api_key: str) -> list[dict]:
    response = requests.post(
        "https://api.tavily.com/search",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"query": query, "max_results": 5},
        timeout=10,
    )
    response.raise_for_status()
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "description": r.get("content", ""),
            "extra_snippets": [],
        }
        for r in response.json().get("results", [])
    ]


def _brave_search(query: str, api_key: str) -> list[dict]:
    response = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        headers={"X-Subscription-Token": api_key},
        params={"q": query, "count": 5, "extra_snippets": True},
        timeout=10,
    )
    response.raise_for_status()
    return [
        {
            "title": r["title"],
            "url": r["url"],
            "description": r.get("description", ""),
            "extra_snippets": r.get("extra_snippets", []),
        }
        for r in response.json().get("web", {}).get("results", [])
    ]


# Ordered fallback chain: a provider is tried only if its key env is set, and
# any request failure (429 rate limit, timeout, 5xx) falls through to the next.
# Tavily first — LLM-optimized results, 1k free searches/month; Brave second —
# metered since Feb 2026 and rate-limits aggressively, kept as fallback.
_PROVIDERS = (
    ("tavily", "TAVILY_API_KEY", _tavily_search),
    ("brave", "BRAVE_API_KEY", _brave_search),
)


def _run_search(query: str) -> tuple[str, list[dict]]:
    configured = [
        (name, os.getenv(key_env), fn)
        for name, key_env, fn in _PROVIDERS
        if os.getenv(key_env)
    ]
    if not configured:
        logger.error("no search provider configured (TAVILY_API_KEY / BRAVE_API_KEY)")
        raise RuntimeError(
            "Search unavailable: no search provider API key configured"
        )

    last_error: Exception | None = None
    for name, api_key, fn in configured:
        try:
            return name, fn(query, api_key)
        except requests.Timeout as e:
            logger.warning(f"{name} search timed out for: '{query[:80]}'")
            last_error = e
        except requests.RequestException as e:
            logger.warning(f"{name} search failed, trying next provider: {e}")
            last_error = e

    raise RuntimeError(f"Search request failed on all providers: {last_error}") from last_error


def search(query: str) -> str:
    provider, results = _run_search(query)

    logger.info(f"{provider}-search results={len(results)} query='{query[:80]}'")

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
