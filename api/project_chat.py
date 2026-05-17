"""SSE streaming chat for project-scoped RAG conversations with agent selection.

The routed agent acts as an orchestrator: it always sees retrieved document
passages as initial context, and (if the agent declares any `tool_names`) can
run a multi-step tool loop — search the web, crawl URLs, etc. — before
producing its final answer.
"""

import json
import logging

from agents.base import Agent
from agents.router import route as route_agent
from api.session import get_messages, save_messages, get_session_user
from functions import tool_schemas
from functions.tool_router import execute_tool_call
from llm.response_utils import usage_tokens
from observability.context import pop_context, push_context
from observability.metrics import (
    observe_max_tool_calls_reached,
    observe_retrieval_results,
    observe_summarization,
    observe_tool_budget_exhausted,
)
from observability.spans import chat_turn_span
from pipeline.retriever import retrieve
from prompts.project_chat import build_context_block
from services.chat_postprocess_service import (
    schedule_memory_persistence,
    schedule_memory_summary_refresh,
)
from tasks.memory_tasks import invalidate_session_memory_cursor
from utils.streaming import ToolCallProxy, iter_response
from utils.summarizer import summarize_messages

logger = logging.getLogger("api.project_chat")

MAX_PROMPT_TOKENS = 60000
MAX_MESSAGES_BEFORE_SUMMARY = 18

# Tool-loop budgets for the agent orchestrator. Kept lower than general chat —
# the documents already provide the primary evidence, so tools should be a
# targeted supplement, not a search engine replacement.
MAX_REASONING_STEPS = 3
MAX_TOTAL_TOOL_CALLS = 4


def _format_tool_thinking(name: str, args: dict) -> str:
    if name == "search":
        return f'Searching the web for "{args.get("query", "")}"'
    if name == "crawl_website":
        url = args.get("url", "")
        question = args.get("question", "")
        return (
            f"Reading {url}: {question}" if question else f"Reading {url}"
        )
    return f"Running {name}"


def _format_result_summary(name: str, content: str) -> str:
    try:
        data = json.loads(content)
        if isinstance(data, dict) and "error" in data:
            return f"{name} encountered an error: {str(data['error'])[:100]}"
    except (json.JSONDecodeError, TypeError):
        pass
    return f"Received results from {name}"


def _build_agent_tools(agent: Agent) -> list[dict]:
    """Return the OpenAI-style tool schemas the agent is allowed to call."""
    if not agent.tool_names:
        return []
    allowed = set(agent.tool_names)
    selected = [s for s in tool_schemas if s.get("function", {}).get("name") in allowed]
    missing = allowed - {s["function"]["name"] for s in selected}
    if missing:
        logger.warning(
            f"agent '{agent.name}' references unknown tool(s): {sorted(missing)}"
        )
    return selected


def project_chat_stream(
    session_id: str,
    user_message: str,
    project_id: str,
    chunk_count: int = 0,
    agent_name: str | None = None,
):
    """Generator that yields SSE events for a project-scoped chat turn."""
    user_id = get_session_user(session_id)
    context_tokens = push_context(
        chat_type="project",
        user_id=user_id,
        session_id=session_id,
        project_id=project_id,
    )
    _span_ctx = chat_turn_span(span_name="project_chat.turn", chat_type="project")
    _span_ctx.__enter__()
    try:
        messages = get_messages(session_id)

        # 1. Route to agent (pass full conversation for context-aware classification)
        agent = route_agent(user_message, agent_name, messages)
        yield _sse("thinking", json.dumps({"content": f"Routing to {agent.name} agent"}))
        yield _sse("agent", json.dumps({"name": agent.name, "description": agent.description}))
        logger.info(f"using agent: {agent.name}")

        # Always set the agent's system prompt
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = agent.system_prompt

        # 2. Retrieve with agent-specific overrides
        yield _sse(
            "thinking",
            json.dumps({"content": "Searching for relevant passages in your documents..."}),
        )
        try:
            results, retrieval_info = retrieve(
                project_id=project_id,
                query=user_message,
                chunk_count=chunk_count,
                top_k=agent.top_k_override,
                alpha=agent.alpha_override,
                use_hyde=agent.use_hyde,
            )
        except Exception as e:
            logger.error(f"retrieval failed: {e}")
            results = []
            retrieval_info = {"cache_hit": False}
        observe_retrieval_results(agent_name=agent.name, result_count=len(results))

        sources = [
            {"source": r.get("source", ""), "page": r.get("page"), "score": r.get("score", 0)}
            for r in results
        ]
        yield _sse("thinking", json.dumps({"content": f"Found {len(results)} relevant passages"}))
        yield _sse(
            "retrieval",
            json.dumps(
                {
                    "sources": sources,
                    "count": len(results),
                    "cache_hit": bool(retrieval_info.get("cache_hit", False)),
                }
            ),
        )

        # 3. Build the context-augmented message (kept ephemeral)
        context_block = build_context_block(results)
        if agent.context_instructions:
            context_block += f"\n**Instructions:** {agent.context_instructions}\n"

        augmented_message = f"{user_message}\n{context_block}"
        inference_messages = [*messages, {"role": "user", "content": augmented_message}]

        agent_tools = _build_agent_tools(agent)

        # 4. Orchestration loop. Without tools this is a single streaming call;
        # with tools the agent may interleave tool_calls and reasoning.
        full_content = ""
        prompt_tokens = 0
        tools_used: list[str] = []
        reasoning_steps = 0
        total_tool_calls = 0

        try:
            while True:
                content = ""
                tool_calls = None
                usage = None

                gen = iter_response(
                    inference_messages,
                    use_tools=False,
                    tools_override=agent_tools if agent_tools else None,
                )
                try:
                    while True:
                        token = next(gen)
                        content += token
                        yield _sse("token", token)
                except StopIteration as e:
                    content, tool_calls, usage = e.value

                if usage:
                    prompt_tokens, _ = usage_tokens(usage)

                # No tools (either agent has none, or model produced final text)
                if not tool_calls:
                    full_content = content
                    break

                # Tool-loop budget guards
                if reasoning_steps >= MAX_REASONING_STEPS:
                    observe_tool_budget_exhausted(
                        chat_type="project", budget="reasoning_steps"
                    )
                    full_content = yield from _force_final(
                        inference_messages,
                        "You have reached the maximum number of tool-calling steps. "
                        "Do not call more tools. Answer using the document context and "
                        "the tool results you already have.",
                    )
                    break

                if total_tool_calls + len(tool_calls) > MAX_TOTAL_TOOL_CALLS:
                    observe_max_tool_calls_reached(chat_type="project")
                    observe_tool_budget_exhausted(
                        chat_type="project", budget="total_tool_calls"
                    )
                    full_content = yield from _force_final(
                        inference_messages,
                        "Tool budget exhausted. Do not call more tools. Answer using "
                        "the document context and the tool results you already have.",
                    )
                    break

                # Stream tool intent before executing
                for tc in tool_calls:
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    yield _sse(
                        "thinking",
                        json.dumps({"content": _format_tool_thinking(name, args)}),
                    )
                    yield _sse(
                        "tool",
                        json.dumps({"id": tc["id"], "name": name, "args": args}),
                    )
                    tools_used.append(name)

                inference_messages.append(
                    {
                        "role": "assistant",
                        "tool_calls": tool_calls,
                        "content": None,
                    }
                )

                for tc in tool_calls:
                    proxy = ToolCallProxy(tc)
                    result, tool_info = execute_tool_call(proxy)
                    inference_messages.append(result)
                    yield _sse(
                        "tool_result",
                        json.dumps(
                            {
                                "id": tc["id"],
                                "name": tc["function"]["name"],
                                "cache_hit": bool(tool_info.get("cache_hit", False)),
                            }
                        ),
                    )
                    yield _sse(
                        "thinking",
                        json.dumps(
                            {
                                "content": _format_result_summary(
                                    tc["function"]["name"], result.get("content", "")
                                )
                            }
                        ),
                    )

                reasoning_steps += 1
                total_tool_calls += len(tool_calls)

        except Exception as e:
            logger.error(f"project chat failed: {e}")
            yield _sse("error", sanitize_for_client(str(e)))
            save_messages(session_id, messages)
            return

        # Persist only the raw user text + final assistant content (tool turns
        # remain ephemeral so the next turn re-retrieves fresh context).
        messages.append({"role": "user", "content": user_message})
        messages.append({"role": "assistant", "content": full_content})

        summarized = False
        if prompt_tokens > MAX_PROMPT_TOKENS:
            observe_summarization(reason="prompt_tokens")
            updated = summarize_messages(messages)
            messages.clear()
            messages.extend(updated)
            summarized = True
        elif len(messages) > MAX_MESSAGES_BEFORE_SUMMARY:
            observe_summarization(reason="message_count")
            updated = summarize_messages(messages)
            messages.clear()
            messages.extend(updated)
            summarized = True

        if summarized:
            invalidate_session_memory_cursor(session_id)
            schedule_memory_summary_refresh(messages, session_id=session_id)

        save_messages(session_id, messages)

        if user_id:
            schedule_memory_persistence(messages, user_id, session_id=session_id)

        yield _sse(
            "done",
            json.dumps(
                {
                    "agent": agent.name,
                    "sources_used": len(results),
                    "prompt_tokens": prompt_tokens,
                    "structured": agent.structured_output,
                    "tools_used": tools_used,
                }
            ),
        )
    finally:
        _span_ctx.__exit__(None, None, None)
        pop_context(context_tokens)


def _force_final(messages: list[dict], guidance: str):
    """Stream a final answer with tools disabled. Returns the content via generator return."""
    guidance_msg = {"role": "system", "content": guidance}
    messages.append(guidance_msg)
    try:
        content = ""
        gen = iter_response(messages, use_tools=False)
        try:
            while True:
                token = next(gen)
                content += token
                yield _sse("token", token)
        except StopIteration as e:
            content, _, _ = e.value
        return content
    finally:
        if guidance_msg in messages:
            messages.remove(guidance_msg)


def _sse(event: str, data: str) -> str:
    data_lines = "\n".join(f"data: {line}" for line in data.split("\n"))
    return f"event: {event}\n{data_lines}\n\n"
