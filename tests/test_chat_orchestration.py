"""Integration tests for the chat_stream orchestration loop."""

import json
import time

from api import chat as chat_module


def _tool_call(name: str, args: dict, call_id: str) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(args),
        },
    }


def _response_generator(*, content="", tool_calls=None, usage=None):
    def _gen():
        if content:
            yield content
        return content, tool_calls, usage

    return _gen()


def test_chat_stream_executes_only_first_tool_in_sequential_mode(monkeypatch):
    responses = [
        {
            "tool_calls": [
                _tool_call("crawl_website", {"url": "https://example.com"}, "crawl-1"),
                _tool_call("search", {"query": "example company"}, "search-1"),
            ]
        },
        {"content": "Final answer from crawl."},
    ]
    response_index = {"value": 0}
    executed = []
    saved = {}

    def fake_iter_response(messages, use_tools=True):
        current = responses[response_index["value"]]
        response_index["value"] += 1
        return _response_generator(**current)

    def fake_execute_tool_call(proxy):
        executed.append(proxy.function.name)
        return (
            {
                "role": "tool",
                "tool_call_id": proxy.id,
                "content": json.dumps({"content": f"result for {proxy.function.name}"}),
            },
            {"cache_hit": False},
        )

    monkeypatch.setattr(chat_module, "iter_response", fake_iter_response)
    monkeypatch.setattr(chat_module, "execute_tool_call", fake_execute_tool_call)
    monkeypatch.setattr(chat_module, "get_messages", lambda *_: [])
    monkeypatch.setattr(chat_module, "get_session_user", lambda *_: "user-1")
    monkeypatch.setattr(chat_module, "save_messages", lambda session_id, messages: saved.setdefault("messages", messages))
    monkeypatch.setattr(chat_module, "schedule_memory_persistence", lambda *args, **kwargs: None)

    events = list(chat_module.chat_stream("session-1", "check example"))

    assert executed == ["crawl_website"]
    assert sum(1 for event in events if event.startswith("event: tool\n")) == 1
    assert '"name": "crawl_website"' in "".join(events)
    assert '"name": "search"' not in "".join(events)
    assert saved["messages"][1]["tool_calls"][0]["function"]["name"] == "crawl_website"
    assert saved["messages"][-1]["content"] == "Final answer from crawl."


def test_chat_stream_parallel_search_keeps_tool_results_in_request_order(monkeypatch):
    responses = [
        {
            "tool_calls": [
                _tool_call("search", {"query": "slow"}, "search-1"),
                _tool_call("search", {"query": "fast"}, "search-2"),
            ]
        },
        {"content": "Final answer from search."},
    ]
    response_index = {"value": 0}
    saved = {}

    def fake_iter_response(messages, use_tools=True):
        current = responses[response_index["value"]]
        response_index["value"] += 1
        return _response_generator(**current)

    def fake_execute_tool_call(proxy):
        if proxy.function.arguments == json.dumps({"query": "slow"}):
            time.sleep(0.02)
        return (
            {
                "role": "tool",
                "tool_call_id": proxy.id,
                "content": json.dumps({"result": proxy.function.arguments}),
            },
            {"cache_hit": False},
        )

    monkeypatch.setattr(chat_module, "iter_response", fake_iter_response)
    monkeypatch.setattr(chat_module, "execute_tool_call", fake_execute_tool_call)
    monkeypatch.setattr(chat_module, "get_messages", lambda *_: [])
    monkeypatch.setattr(chat_module, "get_session_user", lambda *_: "user-1")
    monkeypatch.setattr(chat_module, "save_messages", lambda session_id, messages: saved.setdefault("messages", messages))
    monkeypatch.setattr(chat_module, "schedule_memory_persistence", lambda *args, **kwargs: None)

    list(chat_module.chat_stream("session-1", "search both"))

    tool_messages = [message for message in saved["messages"] if message.get("role") == "tool"]
    assert [message["tool_call_id"] for message in tool_messages] == ["search-1", "search-2"]


def test_chat_stream_forces_final_answer_when_reasoning_budget_is_exhausted(monkeypatch):
    responses = [
        {"tool_calls": [_tool_call("search", {"query": "one"}, "search-1")]},
        {"tool_calls": [_tool_call("search", {"query": "two"}, "search-2")]},
        {"content": "Budget-limited final answer."},
    ]
    response_index = {"value": 0}
    use_tools_history = []
    executed = []
    saved = {}

    def fake_iter_response(messages, use_tools=True):
        use_tools_history.append(use_tools)
        current = responses[response_index["value"]]
        response_index["value"] += 1
        return _response_generator(**current)

    def fake_execute_tool_call(proxy):
        executed.append(proxy.function.name)
        return (
            {
                "role": "tool",
                "tool_call_id": proxy.id,
                "content": json.dumps({"result": proxy.function.arguments}),
            },
            {"cache_hit": False},
        )

    monkeypatch.setattr(chat_module, "iter_response", fake_iter_response)
    monkeypatch.setattr(chat_module, "execute_tool_call", fake_execute_tool_call)
    monkeypatch.setattr(chat_module, "get_messages", lambda *_: [])
    monkeypatch.setattr(chat_module, "get_session_user", lambda *_: "user-1")
    monkeypatch.setattr(chat_module, "save_messages", lambda session_id, messages: saved.setdefault("messages", messages))
    monkeypatch.setattr(chat_module, "schedule_memory_persistence", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_module, "MAX_REASONING_STEPS", 1)
    monkeypatch.setattr(chat_module, "MAX_TOTAL_TOOL_CALLS", 6)

    events = list(chat_module.chat_stream("session-1", "keep searching"))

    assert executed == ["search"]
    assert use_tools_history == [True, True, False]
    assert "Budget-limited final answer." in "".join(events)
    assert saved["messages"][-1]["content"] == "Budget-limited final answer."


def test_chat_stream_refreshes_summary_after_summarization(monkeypatch):
    saved = {}
    invalidated = []
    refreshed = []

    def fake_iter_response(messages, use_tools=True):
        return _response_generator(
            content="Final answer.",
            usage={"prompt_tokens": 99999, "completion_tokens": 10},
        )

    monkeypatch.setattr(chat_module, "iter_response", fake_iter_response)
    monkeypatch.setattr(chat_module, "get_messages", lambda *_: [{"role": "system", "content": "sys"}])
    monkeypatch.setattr(chat_module, "get_session_user", lambda *_: "user-1")
    monkeypatch.setattr(
        chat_module,
        "save_messages",
        lambda session_id, messages: saved.setdefault("messages", list(messages)),
    )
    monkeypatch.setattr(
        chat_module,
        "summarize_messages",
        lambda messages: [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "[Previous conversation summary]: summary"},
            {"role": "assistant", "content": "Final answer."},
        ],
    )
    monkeypatch.setattr(
        chat_module,
        "invalidate_session_memory_cursor",
        lambda session_id: invalidated.append(session_id),
    )
    monkeypatch.setattr(
        chat_module,
        "schedule_memory_summary_refresh",
        lambda messages, session_id=None: refreshed.append((list(messages), session_id)),
    )
    monkeypatch.setattr(chat_module, "schedule_memory_persistence", lambda *args, **kwargs: None)

    list(chat_module.chat_stream("session-2", "Summarize this"))

    assert invalidated == ["session-2"]
    assert refreshed == [
        (
            [
                {"role": "system", "content": "sys"},
                {"role": "assistant", "content": "[Previous conversation summary]: summary"},
                {"role": "assistant", "content": "Final answer."},
            ],
            "session-2",
        )
    ]
    assert saved["messages"][1]["content"].startswith("[Previous conversation summary]:")


def test_end_session_with_memory_refreshes_summary(monkeypatch):
    persisted = []
    refreshed = []

    monkeypatch.setattr(chat_module, "get_session_user", lambda *_: "user-7")
    monkeypatch.setattr(
        chat_module,
        "get_messages",
        lambda *_: [{"role": "user", "content": "I use FastAPI."}],
    )
    monkeypatch.setattr(
        chat_module,
        "schedule_memory_summary_refresh",
        lambda messages, session_id=None: refreshed.append((messages, session_id)),
    )
    monkeypatch.setattr(
        chat_module,
        "schedule_memory_persistence",
        lambda messages, user_id, session_id=None: persisted.append(
            (messages, user_id, session_id)
        ),
    )

    chat_module.end_session_with_memory("session-7")

    assert refreshed == [
        ([{"role": "user", "content": "I use FastAPI."}], "session-7")
    ]
    assert persisted == [
        ([{"role": "user", "content": "I use FastAPI."}], "user-7", "session-7")
    ]
