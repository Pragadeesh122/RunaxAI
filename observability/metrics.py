"""Prometheus metric definitions + helper emitters for observability."""

from __future__ import annotations

import os
from typing import Any

from prometheus_client import Counter, Histogram

from observability.context import (
    get_chat_type,
    get_project_hash,
    get_session_hash,
    get_user_hash,
)

try:
    from litellm import cost_per_token
except Exception:  # pragma: no cover - import failure path
    cost_per_token = None


def _env_bool(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() not in {"0", "false", "no", "off"}


OBS_ENABLE_HIGH_CARDINALITY_METRICS = _env_bool(
    "OBS_ENABLE_HIGH_CARDINALITY_METRICS", "true"
)

TTFT_BUCKETS = (0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0)
TOKENS_PER_SEC_BUCKETS = (5, 10, 20, 30, 40, 50, 75, 100, 150)

LLM_REQUESTS_TOTAL = Counter(
    "agenticrag_llm_requests_total",
    "Total LLM requests by outcome.",
    ["operation", "provider", "model", "stream", "status", "chat_type"],
)
LLM_REQUEST_DURATION_SECONDS = Histogram(
    "agenticrag_llm_request_duration_seconds",
    "LLM request duration in seconds.",
    ["operation", "provider", "model", "stream", "status", "chat_type"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 10, 20, 30, 60),
)
LLM_TOKENS_TOTAL = Counter(
    "agenticrag_llm_tokens_total",
    "Prompt/completion token volume.",
    ["provider", "model", "token_type", "chat_type"],
)
LLM_SPEND_USD_TOTAL = Counter(
    "agenticrag_llm_spend_usd_total",
    "Estimated LLM spend in USD.",
    ["provider", "model", "chat_type"],
)
LLM_TTFT_SECONDS = Histogram(
    "agenticrag_llm_ttft_seconds",
    "Time-to-first-token for streaming responses.",
    ["provider", "model", "chat_type"],
    buckets=TTFT_BUCKETS,
)
LLM_OUTPUT_TOKENS_PER_SECOND = Histogram(
    "agenticrag_llm_output_tokens_per_second",
    "Streaming output token generation speed.",
    ["provider", "model", "chat_type"],
    buckets=TOKENS_PER_SEC_BUCKETS,
)
LLM_SESSION_TOKENS_TOTAL = Counter(
    "agenticrag_llm_session_tokens_total",
    "High-cardinality session token totals.",
    ["session_hash", "user_hash", "project_hash", "chat_type"],
)
LLM_SESSION_SPEND_USD_TOTAL = Counter(
    "agenticrag_llm_session_spend_usd_total",
    "High-cardinality session spend totals in USD.",
    ["session_hash", "user_hash", "project_hash", "chat_type"],
)

TOOL_CALLS_TOTAL = Counter(
    "agenticrag_tool_calls_total",
    "Tool execution attempts by outcome.",
    ["tool_name", "status"],
)
TOOL_DURATION_SECONDS = Histogram(
    "agenticrag_tool_duration_seconds",
    "Tool execution duration in seconds.",
    ["tool_name", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30),
)
TOOL_CACHE_TOTAL = Counter(
    "agenticrag_tool_cache_total",
    "Tool cache behavior.",
    ["tool_name", "cache_status"],
)

AGENT_ROUTES_TOTAL = Counter(
    "agenticrag_agent_routes_total",
    "Agent routing decisions.",
    ["selected_agent", "route_mode", "status"],
)
AGENT_ROUTE_DURATION_SECONDS = Histogram(
    "agenticrag_agent_route_duration_seconds",
    "Agent routing latency in seconds.",
    ["route_mode", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)

MAX_TOOL_CALLS_REACHED_TOTAL = Counter(
    "agenticrag_max_tool_calls_reached_total",
    "Count of turns that hit max tool call budget.",
    ["chat_type"],
)
SUMMARIZATION_EVENTS_TOTAL = Counter(
    "agenticrag_summarization_events_total",
    "Conversation summarization trigger count.",
    ["chat_type", "reason"],
)
RETRIEVAL_RESULTS_COUNT = Histogram(
    "agenticrag_retrieval_results_count",
    "Retrieved document chunk count per query.",
    ["agent_name"],
    buckets=(0, 1, 2, 3, 5, 8, 10, 15, 20, 30, 50, 100),
)
RETRIEVAL_DURATION_SECONDS = Histogram(
    "agenticrag_retrieval_duration_seconds",
    "End-to-end RAG retrieval latency in seconds (cache lookup + vector search "
    "+ rerank), labelled by whether the semantic cache served the result.",
    ["cache_status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 10),
)
SESSION_BUDGET_BLOCKED_TOTAL = Counter(
    "agenticrag_session_budget_blocked_total",
    "Chat turns refused because a per-session spend guardrail ceiling was reached.",
    ["chat_type", "limit"],
)
ORCHESTRATION_STEPS_TOTAL = Counter(
    "agenticrag_orchestration_steps_total",
    "General-chat orchestration step planning decisions.",
    ["mode", "reason"],
)
ORCHESTRATION_TOOL_SELECTION_TOTAL = Counter(
    "agenticrag_orchestration_tool_selection_total",
    "Requested, executed, or suppressed tool-call counts during orchestration.",
    ["mode", "selection"],
)
ORCHESTRATION_DUPLICATE_SUPPRESSIONS_TOTAL = Counter(
    "agenticrag_orchestration_duplicate_suppressions_total",
    "Duplicate tool-call suppressions by tool name.",
    ["tool_name"],
)
TOOL_BUDGET_EXHAUSTED_TOTAL = Counter(
    "agenticrag_tool_budget_exhausted_total",
    "Count of turns that exhausted an orchestration budget.",
    ["chat_type", "budget"],
)


def _field(obj: Any, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _usage_tokens(usage: Any) -> tuple[int, int]:
    prompt = int(_field(usage, "prompt_tokens", 0) or 0)
    completion = int(_field(usage, "completion_tokens", 0) or 0)
    return prompt, completion


def estimate_cost_usd(
    *, provider: str, model: str, usage: Any, operation: str = "completion"
) -> float | None:
    if cost_per_token is None:
        return None
    prompt_tokens, completion_tokens = _usage_tokens(usage)
    if prompt_tokens <= 0 and completion_tokens <= 0:
        return None
    full_model = model if "/" in model else f"{provider}/{model}"
    call_type = "embedding" if operation == "embedding" else "completion"
    try:
        prompt_cost, completion_cost = cost_per_token(
            model=full_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            call_type=call_type,
        )
        return float(prompt_cost) + float(completion_cost)
    except Exception:
        return None


def observe_llm_outcome(
    *,
    operation: str,
    provider: str,
    model: str,
    stream: bool,
    status: str,
    duration_seconds: float,
    usage: Any | None = None,
    cost_usd: float | None = None,
) -> None:
    chat_type = get_chat_type()
    stream_label = "true" if stream else "false"
    LLM_REQUESTS_TOTAL.labels(
        operation=operation,
        provider=provider,
        model=model,
        stream=stream_label,
        status=status,
        chat_type=chat_type,
    ).inc()
    LLM_REQUEST_DURATION_SECONDS.labels(
        operation=operation,
        provider=provider,
        model=model,
        stream=stream_label,
        status=status,
        chat_type=chat_type,
    ).observe(duration_seconds)

    if usage is None:
        return

    prompt_tokens, completion_tokens = _usage_tokens(usage)
    if prompt_tokens > 0:
        LLM_TOKENS_TOTAL.labels(
            provider=provider,
            model=model,
            token_type="prompt",
            chat_type=chat_type,
        ).inc(prompt_tokens)
    if completion_tokens > 0:
        LLM_TOKENS_TOTAL.labels(
            provider=provider,
            model=model,
            token_type="completion",
            chat_type=chat_type,
        ).inc(completion_tokens)

    if cost_usd is None:
        cost_usd = estimate_cost_usd(
            provider=provider,
            model=model,
            usage=usage,
            operation=operation,
        )
    if cost_usd and cost_usd > 0:
        LLM_SPEND_USD_TOTAL.labels(
            provider=provider,
            model=model,
            chat_type=chat_type,
        ).inc(cost_usd)

    if not OBS_ENABLE_HIGH_CARDINALITY_METRICS:
        return

    session_hash = get_session_hash()
    if session_hash == "unknown":
        return

    user_hash = get_user_hash()
    project_hash = get_project_hash()
    total_tokens = max(0, prompt_tokens) + max(0, completion_tokens)
    if total_tokens > 0:
        LLM_SESSION_TOKENS_TOTAL.labels(
            session_hash=session_hash,
            user_hash=user_hash,
            project_hash=project_hash,
            chat_type=chat_type,
        ).inc(total_tokens)

    if cost_usd and cost_usd > 0:
        LLM_SESSION_SPEND_USD_TOTAL.labels(
            session_hash=session_hash,
            user_hash=user_hash,
            project_hash=project_hash,
            chat_type=chat_type,
        ).inc(cost_usd)


def observe_llm_ttft(*, provider: str, model: str, seconds: float) -> None:
    if seconds < 0:
        return
    LLM_TTFT_SECONDS.labels(
        provider=provider,
        model=model,
        chat_type=get_chat_type(),
    ).observe(seconds)


def observe_llm_output_speed(*, provider: str, model: str, tokens_per_second: float) -> None:
    if tokens_per_second <= 0:
        return
    LLM_OUTPUT_TOKENS_PER_SECOND.labels(
        provider=provider,
        model=model,
        chat_type=get_chat_type(),
    ).observe(tokens_per_second)


def observe_tool_cache(*, tool_name: str, cache_status: str) -> None:
    TOOL_CACHE_TOTAL.labels(tool_name=tool_name, cache_status=cache_status).inc()


def observe_tool_outcome(*, tool_name: str, status: str, duration_seconds: float) -> None:
    TOOL_CALLS_TOTAL.labels(tool_name=tool_name, status=status).inc()
    if duration_seconds >= 0:
        TOOL_DURATION_SECONDS.labels(tool_name=tool_name, status=status).observe(
            duration_seconds
        )


def observe_agent_route(
    *, selected_agent: str, route_mode: str, status: str, duration_seconds: float
) -> None:
    AGENT_ROUTES_TOTAL.labels(
        selected_agent=selected_agent, route_mode=route_mode, status=status
    ).inc()
    AGENT_ROUTE_DURATION_SECONDS.labels(
        route_mode=route_mode, status=status
    ).observe(max(duration_seconds, 0.0))


def observe_max_tool_calls_reached(*, chat_type: str) -> None:
    MAX_TOOL_CALLS_REACHED_TOTAL.labels(chat_type=chat_type or "unknown").inc()


def observe_summarization(*, reason: str) -> None:
    SUMMARIZATION_EVENTS_TOTAL.labels(
        chat_type=get_chat_type(), reason=reason
    ).inc()


def observe_retrieval_results(*, agent_name: str, result_count: int) -> None:
    RETRIEVAL_RESULTS_COUNT.labels(agent_name=(agent_name or "unknown")).observe(
        max(result_count, 0)
    )


def observe_retrieval_latency(*, cache_hit: bool, duration_seconds: float) -> None:
    if duration_seconds < 0:
        return
    RETRIEVAL_DURATION_SECONDS.labels(
        cache_status="hit" if cache_hit else "miss"
    ).observe(duration_seconds)


def observe_session_budget_blocked(*, chat_type: str, limit: str) -> None:
    SESSION_BUDGET_BLOCKED_TOTAL.labels(
        chat_type=chat_type or "unknown",
        limit=limit or "unknown",
    ).inc()


def observe_orchestration_step(
    *,
    mode: str,
    reason: str,
    requested_calls: int,
    executed_calls: int,
    suppressed_calls: int,
) -> None:
    ORCHESTRATION_STEPS_TOTAL.labels(
        mode=mode or "unknown",
        reason=reason or "unknown",
    ).inc()

    if requested_calls > 0:
        ORCHESTRATION_TOOL_SELECTION_TOTAL.labels(
            mode=mode or "unknown",
            selection="requested",
        ).inc(requested_calls)
    if executed_calls > 0:
        ORCHESTRATION_TOOL_SELECTION_TOTAL.labels(
            mode=mode or "unknown",
            selection="executed",
        ).inc(executed_calls)
    if suppressed_calls > 0:
        ORCHESTRATION_TOOL_SELECTION_TOTAL.labels(
            mode=mode or "unknown",
            selection="suppressed",
        ).inc(suppressed_calls)


def observe_orchestration_duplicate_suppression(*, tool_name: str) -> None:
    ORCHESTRATION_DUPLICATE_SUPPRESSIONS_TOTAL.labels(
        tool_name=tool_name or "unknown"
    ).inc()


def observe_tool_budget_exhausted(*, chat_type: str, budget: str) -> None:
    TOOL_BUDGET_EXHAUSTED_TOTAL.labels(
        chat_type=chat_type or "unknown",
        budget=budget or "unknown",
    ).inc()
