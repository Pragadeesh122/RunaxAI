"""Anonymous Parallel Search MCP adapter for the existing search tool."""

import asyncio

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

_MCP_URL = "https://search.parallel.ai/mcp"
_USER_AGENT = "RunaxAI/0.1.0 (https://github.com/Pragadeesh122/RunaxAI)"
_TIMEOUT_SECONDS = 10


async def _search(query: str) -> list[dict]:
    # Bound the whole operation, including discovery and connection cleanup.
    async with asyncio.timeout(_TIMEOUT_SECONDS):
        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT_SECONDS
        ) as client:
            async with streamable_http_client(_MCP_URL, http_client=client) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    response = await session.call_tool(
                        "web_search",
                        arguments={"objective": query, "search_queries": [query]},
                    )

    if response.isError:
        raise RuntimeError("Parallel search returned an error; try again later")
    payload = response.structuredContent
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise RuntimeError("Parallel search returned invalid results")

    return [
        {
            "title": result.get("title") or "",
            "url": result["url"],
            "description": "\n".join(result["excerpts"]),
            "extra_snippets": [],
        }
        for result in payload["results"][:5]
    ]


def parallel_search(query: str) -> list[dict]:
    """Run keyless search in the synchronous tool router's worker thread."""
    try:
        return asyncio.run(_search(query))
    except TimeoutError as exc:
        raise RuntimeError("Parallel search timed out") from exc
