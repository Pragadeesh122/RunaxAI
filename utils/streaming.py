import re
import sys
import logging
import os
from clients import llm_client
from tools import tools
from llm.factory import get_llm_registry

logger = logging.getLogger("orchestrator")
ORCHESTRATOR_MODEL = os.getenv("ORCHESTRATOR_MODEL", "gpt-5.4")
_STREAM_USAGE_PROVIDERS = {"openai", "grok"}

# Matches any URL carrying an AWS/MinIO presigned signature. We never want
# these to reach the browser via error events — the signature is a 10-minute
# bearer token that grants read access to the underlying object.
_PRESIGNED_URL_RE = re.compile(
    r"https?://\S*?[?&]X-Amz-Signature=[A-Fa-f0-9]+\S*",
)


def sanitize_for_client(text: str) -> str:
    """Strip presigned storage URLs from any string heading to the browser."""
    if not text:
        return text
    return _PRESIGNED_URL_RE.sub("[storage URL redacted]", text)


def _field(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _extract_delta(chunk):
    choices = _field(chunk, "choices", None)
    if not choices:
        return None
    first_choice = choices[0]
    return _field(first_choice, "delta", None)


def _extract_usage(chunk):
    return _field(chunk, "usage", None)


def _provider_for_model(model):
    try:
        return get_llm_registry().resolve_chat(model).provider.name
    except Exception:
        return ""


def _has_tool_history(messages):
    """Return True when conversation already contains tool-call blocks."""
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") == "tool":
            return True
        if msg.get("tool_calls"):
            return True
    return False


def stream_response(messages, model=None, use_tools=True, tools_override=None):
    """Stream an LLM response, printing text tokens as they arrive.

    Returns (content, tool_calls, usage) where:
    - content: full text response (or None if tool calls)
    - tool_calls: list of tool call objects (or None if text)
    - usage: token usage dict

    `tools_override` (when provided) replaces the global tool list — used by
    agent-scoped orchestrators that expose only a subset of tools.
    """
    resolved_model = model or ORCHESTRATOR_MODEL
    kwargs = {
        "model": resolved_model,
        "messages": messages,
        "stream": True,
    }
    if _provider_for_model(resolved_model) in _STREAM_USAGE_PROVIDERS:
        kwargs["stream_options"] = {"include_usage": True}
    if tools_override is not None:
        if tools_override:
            kwargs["tools"] = tools_override
        elif _provider_for_model(resolved_model) == "anthropic" and _has_tool_history(
            messages
        ):
            kwargs["tools"] = []
    elif use_tools:
        kwargs["tools"] = tools
    elif _provider_for_model(resolved_model) == "anthropic" and _has_tool_history(
        messages
    ):
        # Anthropic can require an explicit tools field when prior turns include tool messages.
        kwargs["tools"] = []

    stream = llm_client.chat.completions.create(**kwargs)

    content = ""
    tool_calls_by_index = {}
    usage = None

    for chunk in stream:
        # Capture usage from the final chunk
        chunk_usage = _extract_usage(chunk)
        if chunk_usage:
            usage = chunk_usage

        delta = _extract_delta(chunk)
        if not delta:
            continue

        # Stream text content to stdout immediately
        delta_content = _field(delta, "content", None)
        if delta_content:
            sys.stdout.write(delta_content)
            sys.stdout.flush()
            content += delta_content

        # Accumulate tool call deltas
        delta_tool_calls = _field(delta, "tool_calls", None)
        if delta_tool_calls:
            for tc_delta in delta_tool_calls:
                idx = _field(tc_delta, "index", 0)
                if idx not in tool_calls_by_index:
                    tool_calls_by_index[idx] = {
                        "id": _field(tc_delta, "id", "") or "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    }
                tc = tool_calls_by_index[idx]
                tc_id = _field(tc_delta, "id", None)
                if tc_id:
                    tc["id"] = tc_id
                tc_function = _field(tc_delta, "function", None)
                if tc_function:
                    fn_name = _field(tc_function, "name", "")
                    fn_arguments = _field(tc_function, "arguments", "")
                    if fn_name:
                        tc["function"]["name"] += fn_name
                    if fn_arguments:
                        tc["function"]["arguments"] += fn_arguments

    if content:
        sys.stdout.write("\n")
        sys.stdout.flush()

    if usage:
        prompt_tokens = _field(usage, "prompt_tokens", 0)
        completion_tokens = _field(usage, "completion_tokens", 0)
        logger.info(
            f"llm  model={resolved_model} tokens_in={prompt_tokens} tokens_out={completion_tokens}"
        )

    # Build tool_calls list sorted by index
    if tool_calls_by_index:
        sorted_tcs = [tool_calls_by_index[i] for i in sorted(tool_calls_by_index)]
        return None, sorted_tcs, usage

    return content, None, usage


def iter_response(messages, model=None, use_tools=True, tools_override=None):
    """Yield text tokens as they arrive, then return tool_calls and usage.

    Yields:
        str: each text token as it arrives

    Returns via generator .value (use wrapper to capture):
        (content, tool_calls, usage)

    `tools_override` (when provided) replaces the global tool list — used by
    agent-scoped orchestrators that expose only a subset of tools.
    """
    resolved_model = model or ORCHESTRATOR_MODEL
    kwargs = {
        "model": resolved_model,
        "messages": messages,
        "stream": True,
    }
    if _provider_for_model(resolved_model) in _STREAM_USAGE_PROVIDERS:
        kwargs["stream_options"] = {"include_usage": True}
    if tools_override is not None:
        if tools_override:
            kwargs["tools"] = tools_override
        elif _provider_for_model(resolved_model) == "anthropic" and _has_tool_history(
            messages
        ):
            kwargs["tools"] = []
    elif use_tools:
        kwargs["tools"] = tools
    elif _provider_for_model(resolved_model) == "anthropic" and _has_tool_history(
        messages
    ):
        # Anthropic can require an explicit tools field when prior turns include tool messages.
        kwargs["tools"] = []

    stream = llm_client.chat.completions.create(**kwargs)

    content = ""
    tool_calls_by_index = {}
    usage = None

    try:
        for chunk in stream:
            chunk_usage = _extract_usage(chunk)
            if chunk_usage:
                usage = chunk_usage

            delta = _extract_delta(chunk)
            if not delta:
                continue

            delta_content = _field(delta, "content", None)
            if delta_content:
                yield delta_content
                content += delta_content

            delta_tool_calls = _field(delta, "tool_calls", None)
            if delta_tool_calls:
                for tc_delta in delta_tool_calls:
                    idx = _field(tc_delta, "index", 0)
                    if idx not in tool_calls_by_index:
                        tool_calls_by_index[idx] = {
                            "id": _field(tc_delta, "id", "") or "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    tc = tool_calls_by_index[idx]
                    tc_id = _field(tc_delta, "id", None)
                    if tc_id:
                        tc["id"] = tc_id
                    tc_function = _field(tc_delta, "function", None)
                    if tc_function:
                        fn_name = _field(tc_function, "name", "")
                        fn_arguments = _field(tc_function, "arguments", "")
                        if fn_name:
                            tc["function"]["name"] += fn_name
                        if fn_arguments:
                            tc["function"]["arguments"] += fn_arguments
    finally:
        close_stream = getattr(stream, "close", None)
        if callable(close_stream):
            try:
                close_stream()
            except Exception:
                logger.debug("failed to close LLM stream", exc_info=True)

    if usage:
        prompt_tokens = _field(usage, "prompt_tokens", 0)
        completion_tokens = _field(usage, "completion_tokens", 0)
        logger.info(
            f"llm  model={resolved_model} tokens_in={prompt_tokens} tokens_out={completion_tokens}"
        )

    tool_calls = None
    if tool_calls_by_index:
        tool_calls = [tool_calls_by_index[i] for i in sorted(tool_calls_by_index)]

    return content, tool_calls, usage


class ToolCallProxy:
    """Lightweight wrapper so execute_tool_call can access .id, .function.name, .function.arguments."""

    def __init__(self, tc_dict):
        self.id = tc_dict["id"]
        self.function = type(
            "Fn",
            (),
            {
                "name": tc_dict["function"]["name"],
                "arguments": tc_dict["function"]["arguments"],
            },
        )()
