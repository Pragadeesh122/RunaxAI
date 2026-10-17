"""Exercise provider selection through real MCP request/response handling."""

import asyncio
import importlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from functions import available_functions
from functions import tool_router
from functions import _parallel_search as parallel

search_module = importlib.import_module("functions.search")

RESULTS = {
    "results": [
        {
            "title": "Python release",
            "url": "https://www.python.org/downloads/",
            "excerpts": ["Release announcement", "Release date"],
        }
    ]
}


@pytest.fixture
def mcp_server(monkeypatch):
    state = {"payload": RESULTS, "error": False, "status": 200, "sse": False}
    requests = []
    clients = []
    real_client = httpx.AsyncClient

    async def handle(request):
        body = json.loads(request.content)
        requests.append((request, body))
        method = body["method"]
        if method.startswith("notifications/"):
            return httpx.Response(202)
        if method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "test-search", "version": "1.0"},
            }
        elif method == "tools/list":
            result = {"tools": [{"name": "web_search", "inputSchema": {"type": "object"}}]}
        else:
            assert method == "tools/call"
            if state.get("wait"):
                state["started"].set()
                await asyncio.Event().wait()
            if state["status"] != 200:
                return httpx.Response(state["status"], text="Service unavailable")
            result = {
                "isError": state["error"],
                "content": [{"type": "text", "text": json.dumps(state["payload"])}],
                "structuredContent": state["payload"],
            }
        response = {"jsonrpc": "2.0", "id": body["id"], "result": result}
        if state["sse"]:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text="event: message\ndata: " + json.dumps(response) + "\n\n",
            )
        return httpx.Response(200, json=response)

    def create_client(**kwargs):
        client = real_client(transport=httpx.MockTransport(handle), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(parallel.httpx, "AsyncClient", create_client)
    monkeypatch.setenv("SEARCH_PROVIDER", "parallel")
    for key in ("TAVILY_API_KEY", "BRAVE_API_KEY", "PARALLEL_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    return state, requests, clients


def tool_call():
    return SimpleNamespace(
        id="search-1",
        function=SimpleNamespace(
            name="search", arguments=json.dumps({"query": "latest Python release"})
        ),
    )


@pytest.mark.parametrize("sse", [False, True])
def test_registered_search_consumes_anonymous_mcp_results(mcp_server, monkeypatch, sse):
    state, requests, clients = mcp_server
    state["sse"] = sse
    monkeypatch.setenv("SEARCH_PROVIDER", " Parallel ")
    summarize = Mock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Release summary"))],
            usage={},
        )
    )
    monkeypatch.setattr(search_module.llm_client.chat.completions, "create", summarize)
    monkeypatch.setattr(tool_router, "get_cached_result", lambda *args: None)
    cache = Mock()
    monkeypatch.setattr(tool_router, "cache_result", cache)

    assert available_functions["search"] is search_module.search
    message, info = tool_router.execute_tool_call(tool_call())

    assert json.loads(message["content"]) == "Release summary"
    assert info == {"cache_hit": False}
    source_text = summarize.call_args.kwargs["messages"][1]["content"]
    assert "https://www.python.org/downloads/" in source_text
    assert "Release announcement\\nRelease date" in source_text
    cache.assert_called_once_with("search", "latest Python release", message["content"])
    methods = [body["method"] for _, body in requests]
    assert "initialize" in methods and "tools/list" in methods
    calls = [body for _, body in requests if body["method"] == "tools/call"]
    assert calls[0]["params"] == {
        "name": "web_search",
        "arguments": {
            "objective": "latest Python release",
            "search_queries": ["latest Python release"],
        },
    }
    for request, _ in requests:
        assert str(request.url) == "https://search.parallel.ai/mcp"
        assert request.headers["user-agent"] == parallel._USER_AGENT
        assert "authorization" not in request.headers
        assert "x-api-key" not in request.headers
    assert all(client.is_closed for client in clients)


def test_empty_results_skip_summarization(mcp_server, monkeypatch):
    state, _, _ = mcp_server
    state["payload"] = {"results": []}
    summarize = Mock()
    monkeypatch.setattr(search_module.llm_client.chat.completions, "create", summarize)
    assert search_module.search("no results") == "No search results found for: 'no results'"
    summarize.assert_not_called()


def test_excerpts_survive_summarizer_failure(mcp_server, monkeypatch):
    monkeypatch.setattr(
        search_module.llm_client.chat.completions,
        "create",
        Mock(side_effect=RuntimeError("LLM unavailable")),
    )
    result = search_module.search("latest Python release")
    assert "https://www.python.org/downloads/" in result
    assert "Release announcement" in result


@pytest.mark.parametrize("failure", ["tool_error", "http_error", "invalid_results"])
def test_errors_reach_router_without_keyed_fallback(mcp_server, monkeypatch, failure):
    state, _, clients = mcp_server
    if failure == "tool_error":
        state["error"] = True
    elif failure == "http_error":
        state["status"] = 429
    else:
        state["payload"] = {"results": "invalid"}
    monkeypatch.setenv("TAVILY_API_KEY", "must-not-be-used")
    keyed_request = Mock(side_effect=AssertionError("unexpected keyed fallback"))
    monkeypatch.setattr(search_module.requests, "post", keyed_request)
    monkeypatch.setattr(tool_router, "get_cached_result", lambda *args: None)
    cache = Mock()
    monkeypatch.setattr(tool_router, "cache_result", cache)

    message, _ = tool_router.execute_tool_call(tool_call())
    assert "error" in json.loads(message["content"])
    cache.assert_not_called()
    keyed_request.assert_not_called()
    assert all(client.is_closed for client in clients)


def test_deadline_closes_client(mcp_server, monkeypatch):
    state, _, clients = mcp_server
    state.update(wait=True, started=asyncio.Event())
    monkeypatch.setattr(parallel, "_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(RuntimeError, match="Parallel search timed out"):
        search_module._run_search("slow search")
    assert clients and all(client.is_closed for client in clients)


def test_cancellation_propagates_and_closes_client(mcp_server):
    state, _, clients = mcp_server

    async def cancel_search():
        state.update(wait=True, started=asyncio.Event())
        task = asyncio.create_task(parallel._search("cancel search"))
        await asyncio.wait_for(state["started"].wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_search())
    assert clients and all(client.is_closed for client in clients)


@pytest.mark.parametrize("selection", [None, "", " "])
def test_unselected_parallel_preserves_default_chain(monkeypatch, selection):
    if selection is None:
        monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    else:
        monkeypatch.setenv("SEARCH_PROVIDER", selection)
    monkeypatch.setenv("TAVILY_API_KEY", "existing-key")
    parallel_call = Mock(side_effect=AssertionError("Parallel was not selected"))
    monkeypatch.setattr(search_module, "parallel_search", parallel_call)
    provider = Mock(return_value=RESULTS["results"])
    monkeypatch.setattr(search_module, "_PROVIDERS", (("tavily", "TAVILY_API_KEY", provider),))
    name, _ = search_module._run_search("query")
    assert name == "tavily"
    provider.assert_called_once_with("query", "existing-key")
    parallel_call.assert_not_called()
