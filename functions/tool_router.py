import json
import logging
import time
from functions import available_functions, cacheable_tools
from memory.cache import get_cached_result, cache_result
from observability.metrics import observe_tool_cache, observe_tool_outcome
from observability.spans import tool_span

logger = logging.getLogger("tool-router")


def execute_tool_call(tool_call) -> tuple[dict, dict]:
    """Execute a tool call.

    Returns:
        Tuple of (message, info) where:
          - message: standard tool result dict for the LLM message history
          - info: {"cache_hit": bool} — whether result came from the tool cache
    """
    name = tool_call.function.name
    started = time.perf_counter()
    with tool_span(tool_name=name or "unknown") as span:
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as e:
            logger.error(f"failed to parse arguments for {name}: {e}")
            observe_tool_outcome(
                tool_name=name or "unknown",
                status="error",
                duration_seconds=time.perf_counter() - started,
            )
            if span is not None:
                span.set_attribute("status", "error")
            return (
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps({"error": f"Invalid arguments: {e}"}),
                },
                {"cache_hit": False},
            )

        if name not in available_functions:
            logger.error(f"unknown tool: {name}")
            observe_tool_outcome(
                tool_name=name or "unknown",
                status="error",
                duration_seconds=time.perf_counter() - started,
            )
            if span is not None:
                span.set_attribute("status", "error")
            return (
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps({"error": f"Unknown tool: {name}"}),
                },
                {"cache_hit": False},
            )

        # Check cache for similar queries (the cache module logs HIT/MISS itself)
        query_str = args.get("query", "")
        if name in cacheable_tools and query_str:
            cached = get_cached_result(name, query_str)
            if cached:
                observe_tool_cache(tool_name=name, cache_status="hit")
                observe_tool_outcome(
                    tool_name=name,
                    status="success",
                    duration_seconds=time.perf_counter() - started,
                )
                if span is not None:
                    span.set_attribute("tool.cache_status", "hit")
                    span.set_attribute("status", "success")
                logger.info(f"tool {name} -> served from cache")
                return (
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": cached,
                    },
                    {"cache_hit": True},
                )
            observe_tool_cache(tool_name=name, cache_status="miss")
            if span is not None:
                span.set_attribute("tool.cache_status", "miss")
        else:
            observe_tool_cache(tool_name=name, cache_status="skip")
            if span is not None:
                span.set_attribute("tool.cache_status", "skip")

        logger.info(f"tool {name} executing args={args}")
        try:
            result = available_functions[name](**args)
            result_str = json.dumps(result)

            # Cache the result
            if name in cacheable_tools and query_str:
                cache_result(name, query_str, result_str)

            observe_tool_outcome(
                tool_name=name,
                status="success",
                duration_seconds=time.perf_counter() - started,
            )
            if span is not None:
                span.set_attribute("status", "success")

            return (
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_str,
                },
                {"cache_hit": False},
            )
        except Exception as e:
            logger.error(f"tool {name} failed: {e}")
            observe_tool_outcome(
                tool_name=name,
                status="error",
                duration_seconds=time.perf_counter() - started,
            )
            if span is not None:
                span.set_attribute("status", "error")
            return (
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps({"error": f"Tool execution failed: {e}"}),
                },
                {"cache_hit": False},
            )
