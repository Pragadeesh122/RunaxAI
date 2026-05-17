"""SSE streaming chat endpoint — runs the full orchestrator loop."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from functions import tool_policies
from functions.tool_router import execute_tool_call
from pipeline.chat_attachments import prepare_messages_for_llm
from utils.streaming import iter_response, ToolCallProxy, sanitize_for_client
from utils.tool_planner import plan_tool_calls
from utils.summarizer import summarize_messages
from api.session import get_messages, save_messages, get_session_user
from llm.response_utils import usage_tokens
from observability.context import pop_context, push_context
from observability.metrics import (
    observe_agent_route,
    observe_max_tool_calls_reached,
    observe_orchestration_duplicate_suppression,
    observe_orchestration_step,
    observe_summarization,
    observe_tool_budget_exhausted,
)
from observability.spans import chat_turn_span
from services.chat_postprocess_service import (
    schedule_memory_persistence,
    schedule_memory_summary_refresh,
)
from tasks.memory_tasks import invalidate_session_memory_cursor

logger = logging.getLogger("api.chat")

MAX_PROMPT_TOKENS = 40000
MAX_REASONING_STEPS = 3
MAX_TOTAL_TOOL_CALLS = 6
MAX_PARALLEL_CALLS_PER_STEP = 3


def _format_tool_thinking(name: str, args: dict) -> str:
    """Format a human-readable thinking step for a tool call."""
    if name == "search":
        return f'Searching the web for "{args.get("query", "")}"'
    elif name == "query_db":
        return f'Querying the database: {args.get("question", "")}'
    elif name == "browser_task":
        url = args.get("url", "")
        goal = args.get("goal", "")
        return f"Browsing {url}: {goal}" if url else f"Browsing: {goal}"
    elif name == "crawl_website":
        url = args.get("url", "")
        question = args.get("question", "")
        return (
            f"Extracting website content from {url}: {question}"
            if question
            else f"Extracting website content from {url}"
        )
    elif name == "query_local_kb":
        return f'Searching knowledge base for "{args.get("query", "")}"'
    elif name == "portfolio":
        return f'Looking up: {args.get("query", "")}'
    else:
        return f"Running {name}"


def _format_result_summary(name: str, content: str) -> str:
    """Format a brief summary of a tool result."""
    try:
        data = json.loads(content)
        if isinstance(data, dict) and "error" in data:
            return f"{name} encountered an error: {data['error'][:100]}"
        if isinstance(data, dict) and "count" in data:
            return f"Received {data['count']} results from {name}"
        if isinstance(data, dict) and "rows" in data:
            return f"Got {len(data['rows'])} rows from database"
        if isinstance(data, list):
            return f"Received {len(data)} results from {name}"
    except (json.JSONDecodeError, TypeError):
        pass
    return f"Received results from {name}"


def _execute_planned_calls(selected_calls, mode: str):
    if not selected_calls:
        return []

    if mode != "parallel" or len(selected_calls) == 1:
        planned = selected_calls[0]
        proxy = ToolCallProxy(planned.tool_call)
        message, info = execute_tool_call(proxy)
        return [(planned, message, info)]

    proxies = [ToolCallProxy(planned.tool_call) for planned in selected_calls]
    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(execute_tool_call, proxy): (planned, proxy)
            for planned, proxy in zip(selected_calls, proxies)
        }
        ordered_results = []
        for future in as_completed(futures):
            planned, proxy = futures[future]
            ordered_results.append((planned, proxy, future.result()))

    order = {planned.tool_call["id"]: index for index, planned in enumerate(selected_calls)}
    ordered_results.sort(key=lambda item: order[item[0].tool_call["id"]])
    return [(planned, result[0], result[1]) for planned, _, result in ordered_results]


def _stream_no_tool_response(messages: list[dict], guidance: str, build_llm_messages=None):
    guidance_msg = {
        "role": "system",
        "content": guidance,
    }
    messages.append(guidance_msg)
    try:
        content = ""
        final_tool_calls = None
        usage = None
        llm_msgs = build_llm_messages() if build_llm_messages else messages
        gen = iter_response(llm_msgs, use_tools=False)
        try:
            while True:
                token = next(gen)
                content += token
                yield _sse("token", token)
        except StopIteration as e:
            content, final_tool_calls, usage = e.value
        return content, final_tool_calls, usage
    finally:
        if guidance_msg in messages:
            messages.remove(guidance_msg)


def _force_final_answer(messages: list[dict], guidance: str, build_llm_messages=None):
    content, final_tool_calls, usage = yield from _stream_no_tool_response(
        messages, guidance, build_llm_messages
    )

    if (not (content or "").strip()) or final_tool_calls:
        logger.warning(
            "final no-tool pass returned empty/tool-calls; retrying with stricter no-tool instruction"
        )
        content, _, usage = yield from _stream_no_tool_response(
            messages,
            (
                "Tool-call budget or orchestration policy has ended further tool use. "
                "Do not call tools. Provide your best final answer using only the "
                "existing tool outputs and conversation context."
            ),
            build_llm_messages,
        )

    if not (content or "").strip():
        logger.warning("final response still empty; sending graceful fallback text")
        content = (
            "I gathered the tool results, but couldn't generate a final response. "
            "Please retry once and I will answer directly."
        )
        yield _sse("token", content)

    return content, usage


def chat_stream(session_id: str, user_message: str, attachments: list[dict] | None = None):
    """Generator that yields SSE-formatted events for a single user turn.

    Event types:
        token     — a chunk of the assistant's text response
        tool      — a tool was called (name + args)
        thinking  — reasoning/activity step
        error     — something went wrong
        done      — final event with metadata
    """
    user_id = get_session_user(session_id)
    context_tokens = push_context(
        chat_type="general",
        session_id=session_id,
        user_id=user_id,
    )
    _span_ctx = chat_turn_span(span_name="chat.turn", chat_type="general")
    _span_ctx.__enter__()
    try:
        observe_agent_route(
            selected_agent="orchestrator",
            route_mode="general",
            status="success",
            duration_seconds=0.0,
        )

        messages = get_messages(session_id)
        attachments = attachments or []
        # Persist attachment refs (not resolved bytes) on the user message in
        # Redis so each historical turn keeps its own attachments. The LLM
        # payload is built fresh each turn by resolving refs per-message —
        # this keeps the conversation flow accurate and lets the summarizer
        # reason about plain text without losing file context.
        user_msg: dict = {"role": "user", "content": user_message}
        if attachments:
            user_msg["attachments"] = attachments
        messages.append(user_msg)

        def messages_for_llm() -> list[dict]:
            return prepare_messages_for_llm(messages)

        reasoning_step_count = 0
        total_tool_calls = 0
        tool_evidence_version = 0
        last_evidence_by_fingerprint: dict[str, int] = {}
        prompt_tokens = 0
        tools_used = []
        full_content = ""

        try:
            while True:
                content = ""
                tool_calls = None
                usage = None

                gen = iter_response(messages_for_llm())
                try:
                    while True:
                        token = next(gen)
                        content += token
                        yield _sse("token", token)
                except StopIteration as e:
                    # iter_response returns (content, tool_calls, usage)
                    content, tool_calls, usage = e.value

                if usage:
                    prompt_tokens, _ = usage_tokens(usage)

                if not tool_calls:
                    full_content = content
                    break

                if reasoning_step_count >= MAX_REASONING_STEPS:
                    logger.info(
                        "max reasoning steps reached (%s)", MAX_REASONING_STEPS
                    )
                    observe_tool_budget_exhausted(
                        chat_type="general", budget="reasoning_steps"
                    )
                    full_content, usage = yield from _force_final_answer(
                        messages,
                        (
                            "You have reached the maximum number of reasoning steps that can "
                            "use tools. Do not call more tools. Respond with the best answer "
                            "you can based on the information already gathered."
                        ),
                        messages_for_llm,
                    )
                    if usage:
                        prompt_tokens, _ = usage_tokens(usage)
                    break

                if total_tool_calls >= MAX_TOTAL_TOOL_CALLS:
                    logger.info(
                        "max total tool calls reached (%s)", MAX_TOTAL_TOOL_CALLS
                    )
                    observe_max_tool_calls_reached(chat_type="general")
                    observe_tool_budget_exhausted(
                        chat_type="general", budget="total_tool_calls"
                    )
                    full_content, usage = yield from _force_final_answer(
                        messages,
                        (
                            "You have reached the maximum number of tool calls. Do not "
                            "attempt any more tool calls. Respond with the best answer "
                            "you can based on the information gathered."
                        ),
                        messages_for_llm,
                    )
                    if usage:
                        prompt_tokens, _ = usage_tokens(usage)
                    break

                plan = plan_tool_calls(
                    tool_calls,
                    tool_policies=tool_policies,
                    last_evidence_by_fingerprint=last_evidence_by_fingerprint,
                    current_evidence_version=tool_evidence_version,
                    max_parallel_calls_per_step=MAX_PARALLEL_CALLS_PER_STEP,
                )
                observe_orchestration_step(
                    mode=plan.mode,
                    reason=plan.reason,
                    requested_calls=plan.requested_count,
                    executed_calls=len(plan.selected_calls),
                    suppressed_calls=len(plan.suppressed_calls),
                )

                for suppressed in plan.suppressed_calls:
                    if suppressed.reason.startswith("duplicate"):
                        observe_orchestration_duplicate_suppression(
                            tool_name=suppressed.planned_call.tool_name
                        )

                if not plan.selected_calls:
                    logger.info("all tool calls suppressed; forcing final answer")
                    full_content, usage = yield from _force_final_answer(
                        messages,
                        (
                            "A repeated or redundant tool call was suppressed because no new "
                            "tool evidence was available. Do not repeat the same tool call. "
                            "Provide your best final answer using the existing tool outputs."
                        ),
                        messages_for_llm,
                    )
                    if usage:
                        prompt_tokens, _ = usage_tokens(usage)
                    break

                if len(plan.selected_calls) > (MAX_TOTAL_TOOL_CALLS - total_tool_calls):
                    logger.info("remaining tool budget is smaller than planned batch")
                    observe_max_tool_calls_reached(chat_type="general")
                    observe_tool_budget_exhausted(
                        chat_type="general", budget="total_tool_calls"
                    )
                    full_content, usage = yield from _force_final_answer(
                        messages,
                        (
                            "The remaining tool budget is exhausted. Do not call more tools. "
                            "Provide your best final answer using the information already gathered."
                        ),
                        messages_for_llm,
                    )
                    if usage:
                        prompt_tokens, _ = usage_tokens(usage)
                    break

                selected_tool_names = [
                    planned.tool_name for planned in plan.selected_calls
                ]
                tools_used.extend(selected_tool_names)
                logger.info(
                    "tool_calls (%s): %s (step %s/%s, total %s/%s)",
                    plan.mode,
                    selected_tool_names,
                    reasoning_step_count + 1,
                    MAX_REASONING_STEPS,
                    total_tool_calls,
                    MAX_TOTAL_TOOL_CALLS,
                )

                for planned in plan.selected_calls:
                    yield _sse(
                        "thinking",
                        json.dumps(
                            {
                                "content": _format_tool_thinking(
                                    planned.tool_name, planned.args
                                )
                            }
                        ),
                    )
                    yield _sse(
                        "tool",
                        json.dumps(
                            {
                                "id": planned.tool_call["id"],
                                "name": planned.tool_name,
                                "args": planned.args,
                            }
                        ),
                    )

                messages.append(
                    {
                        "role": "assistant",
                        "tool_calls": [
                            planned.tool_call for planned in plan.selected_calls
                        ],
                        "content": None,
                    }
                )

                results = _execute_planned_calls(plan.selected_calls, plan.mode)
                for planned, result, info in results:
                    messages.append(result)
                    tool_evidence_version += 1
                    last_evidence_by_fingerprint[
                        planned.fingerprint
                    ] = tool_evidence_version
                    yield _sse(
                        "tool_result",
                        json.dumps(
                            {
                                "id": planned.tool_call["id"],
                                "name": planned.tool_name,
                                "cache_hit": bool(info.get("cache_hit", False)),
                            }
                        ),
                    )
                    result_content = result.get("content", "")
                    summary = _format_result_summary(
                        planned.tool_name, result_content
                    )
                    yield _sse("thinking", json.dumps({"content": summary}))

                reasoning_step_count += 1
                total_tool_calls += len(results)

        except Exception as e:
            logger.error(f"chat failed: {e}")
            yield _sse("error", sanitize_for_client(str(e)))
            # Remove the failed user message
            if messages and messages[-1].get("role") == "user":
                messages.pop()
            save_messages(session_id, messages)
            return

        messages.append({"role": "assistant", "content": full_content})

        # Summarize if token count is high
        if prompt_tokens > MAX_PROMPT_TOKENS:
            observe_summarization(reason="prompt_tokens")
            updated = summarize_messages(messages)
            messages.clear()
            messages.extend(updated)
            # The cursor points at a message that was just collapsed into a
            # summary; invalidate it so the next extraction re-processes the
            # post-summary conversation instead of silently skipping.
            invalidate_session_memory_cursor(session_id)
            schedule_memory_summary_refresh(messages, session_id=session_id)

        save_messages(session_id, messages)

        if user_id:
            schedule_memory_persistence(messages, user_id, session_id=session_id)

        yield _sse(
            "done",
            json.dumps({"tools_used": tools_used, "prompt_tokens": prompt_tokens}),
        )
    finally:
        _span_ctx.__exit__(None, None, None)
        pop_context(context_tokens)


def end_session_with_memory(session_id: str) -> None:
    """Extract memories from the conversation before deleting."""
    try:
        user_id = get_session_user(session_id)
        if not user_id:
            return
        messages = get_messages(session_id)
        schedule_memory_summary_refresh(messages, session_id=session_id)
        schedule_memory_persistence(messages, user_id, session_id=session_id)
    except KeyError:
        pass


def _sse(event: str, data: str) -> str:
    """Format a single SSE event.

    Per SSE spec, multi-line data must use separate 'data:' lines.
    """
    data_lines = "\n".join(f"data: {line}" for line in data.split("\n"))
    return f"event: {event}\n{data_lines}\n\n"
