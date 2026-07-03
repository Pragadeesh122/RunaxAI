"""OpenAI-compatible facade over provider router."""

from __future__ import annotations

import time
import logging
from typing import Any

from llm.factory import LLMProviderRegistry
from observability.metrics import (
    estimate_cost_usd,
    observe_llm_outcome,
    observe_llm_output_speed,
    observe_llm_ttft,
)
from observability.spans import (
    llm_completion_span,
    record_llm_usage,
    record_ttft_event,
)

try:
    from litellm import token_counter
except Exception:  # pragma: no cover - import failure path
    token_counter = None

# Single source of truth for which providers get stream_options: the provider
# layer strips the param for anything outside this set, so a second list here
# would silently drift (request usage -> provider strips it -> estimation).
from llm.providers.litellm_provider import (
    STREAM_OPTIONS_ALLOWED_PROVIDERS as _STREAM_USAGE_PROVIDERS,
)
logger = logging.getLogger(__name__)


def _field(obj: Any, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _extract_usage(obj: Any):
    return _field(obj, "usage", None)


def _extract_delta_content(chunk: Any) -> str:
    choices = _field(chunk, "choices", None)
    if not choices:
        return ""
    first_choice = choices[0]
    delta = _field(first_choice, "delta", None)
    if not delta:
        return ""
    content = _field(delta, "content", "")
    return content or ""


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                    continue
                if item.get("type") == "text" and isinstance(item.get("content"), str):
                    parts.append(item["content"])
        return "".join(parts)
    return ""


def _extract_response_text(response: Any) -> str:
    choices = _field(response, "choices", None)
    if not choices:
        return ""
    first_choice = choices[0]
    message = _field(first_choice, "message", None)
    if message is None:
        return ""
    content = _field(message, "content", "")
    return _content_to_text(content)


def _token_count(
    *,
    model: str,
    text: str | None = None,
    messages: list[dict] | None = None,
    tools: Any | None = None,
    tool_choice: Any | None = None,
) -> int:
    if token_counter is None:
        return 0
    try:
        value = token_counter(
            model=model,
            text=text,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
        )
        return int(value or 0)
    except Exception:
        return 0


def _estimate_usage(
    *,
    model: str,
    messages: list[dict],
    output_text: str,
    tools: Any | None = None,
    tool_choice: Any | None = None,
) -> dict[str, int] | None:
    prompt_tokens = _token_count(
        model=model,
        messages=messages,
        tools=tools,
        tool_choice=tool_choice,
    )
    completion_tokens = _token_count(model=model, text=output_text) if output_text else 0
    if prompt_tokens <= 0 and completion_tokens <= 0:
        return None
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }


class _ChatCompletionsFacade:
    def __init__(self, registry: LLMProviderRegistry):
        self._registry = registry

    def create(
        self,
        *,
        model: str | None = None,
        messages: list[dict],
        stream: bool = False,
        **kwargs: Any,
    ) -> Any:
        resolved = self._registry.resolve_chat(model)
        provider_name = resolved.provider.name
        resolved_model = resolved.model
        call_kwargs = dict(kwargs)

        if (
            stream
            and "stream_options" not in call_kwargs
            and provider_name in _STREAM_USAGE_PROVIDERS
        ):
            call_kwargs["stream_options"] = {"include_usage": True}

        started = time.perf_counter()
        span_ctx = llm_completion_span(
            provider=provider_name,
            model=resolved_model,
            stream=stream,
            operation="completion",
        )
        span = span_ctx.__enter__()
        try:
            response = resolved.provider.chat_completion(
                model=resolved_model,
                messages=messages,
                stream=stream,
                **call_kwargs,
            )
        except Exception:
            observe_llm_outcome(
                operation="completion",
                provider=provider_name,
                model=resolved_model,
                stream=stream,
                status="error",
                duration_seconds=time.perf_counter() - started,
            )
            record_llm_usage(span, usage=None, cost_usd=None, status="error")
            span_ctx.__exit__(None, None, None)
            raise

        if not stream:
            usage = _extract_usage(response)
            status = "success" if usage is not None else "usage_missing"
            if usage is None:
                usage = _estimate_usage(
                    model=resolved_model,
                    messages=messages,
                    output_text=_extract_response_text(response),
                    tools=call_kwargs.get("tools"),
                    tool_choice=call_kwargs.get("tool_choice"),
                )
                if usage is not None:
                    status = "usage_estimated"
            cost_usd = (
                estimate_cost_usd(
                    provider=provider_name,
                    model=resolved_model,
                    usage=usage,
                    operation="completion",
                )
                if usage is not None
                else None
            )
            observe_llm_outcome(
                operation="completion",
                provider=provider_name,
                model=resolved_model,
                stream=False,
                status=status,
                duration_seconds=time.perf_counter() - started,
                usage=usage,
                cost_usd=cost_usd,
            )
            record_llm_usage(span, usage=usage, cost_usd=cost_usd, status=status)
            span_ctx.__exit__(None, None, None)
            return response

        return self._instrument_stream(
            stream_obj=response,
            provider=provider_name,
            model=resolved_model,
            operation="completion",
            started=started,
            messages=messages,
            tools=call_kwargs.get("tools"),
            tool_choice=call_kwargs.get("tool_choice"),
            span=span,
            span_ctx=span_ctx,
        )

    def _instrument_stream(
        self,
        *,
        stream_obj: Any,
        provider: str,
        model: str,
        operation: str,
        started: float,
        messages: list[dict],
        tools: Any | None = None,
        tool_choice: Any | None = None,
        span: Any = None,
        span_ctx: Any = None,
    ):
        def _generator():
            usage = None
            first_token_at = None
            ttft_emitted = False
            ended_at = started
            output_parts: list[str] = []
            _completed = False
            _failed = False
            try:
                for chunk in stream_obj:
                    ended_at = time.perf_counter()
                    delta_content = _extract_delta_content(chunk)
                    if delta_content:
                        output_parts.append(delta_content)
                    if not ttft_emitted and delta_content:
                        ttft = ended_at - started
                        observe_llm_ttft(provider=provider, model=model, seconds=ttft)
                        record_ttft_event(span, ttft_seconds=ttft)
                        first_token_at = ended_at
                        ttft_emitted = True

                    chunk_usage = _extract_usage(chunk)
                    if chunk_usage is not None:
                        usage = chunk_usage

                    yield chunk
                _completed = True
            except Exception:
                _failed = True
                observe_llm_outcome(
                    operation=operation,
                    provider=provider,
                    model=model,
                    stream=True,
                    status="error",
                    duration_seconds=time.perf_counter() - started,
                )
                record_llm_usage(span, usage=None, cost_usd=None, status="error")
                raise
            finally:
                # On normal completion, record usage while the span is still
                # alive, then let span_ctx's finally close it.
                # On error or abandonment, usage was already recorded above.
                if not _completed:
                    close_stream = getattr(stream_obj, "close", None)
                    if callable(close_stream):
                        try:
                            close_stream()
                        except Exception:
                            logger.debug("failed to close abandoned LLM stream", exc_info=True)

                if not _completed and not _failed:
                    observe_llm_outcome(
                        operation=operation,
                        provider=provider,
                        model=model,
                        stream=True,
                        status="cancelled",
                        duration_seconds=time.perf_counter() - started,
                    )
                    record_llm_usage(span, usage=None, cost_usd=None, status="cancelled")

                if _completed:
                    status = "success" if usage is not None else "usage_missing"
                    if usage is None:
                        usage = _estimate_usage(
                            model=model,
                            messages=messages,
                            output_text="".join(output_parts),
                            tools=tools,
                            tool_choice=tool_choice,
                        )
                        if usage is not None:
                            status = "usage_estimated"
                    total_duration = max(ended_at - started, 0.0)
                    cost_usd = (
                        estimate_cost_usd(
                            provider=provider,
                            model=model,
                            usage=usage,
                            operation=operation,
                        )
                        if usage is not None
                        else None
                    )
                    observe_llm_outcome(
                        operation=operation,
                        provider=provider,
                        model=model,
                        stream=True,
                        status=status,
                        duration_seconds=total_duration,
                        usage=usage,
                        cost_usd=cost_usd,
                    )
                    record_llm_usage(span, usage=usage, cost_usd=cost_usd, status=status)

                    if usage is not None and first_token_at is not None:
                        completion_tokens = int(_field(usage, "completion_tokens", 0) or 0)
                        output_elapsed = max(ended_at - first_token_at, 1e-6)
                        if completion_tokens > 0:
                            observe_llm_output_speed(
                                provider=provider,
                                model=model,
                                tokens_per_second=completion_tokens / output_elapsed,
                            )
                # End the span after all attributes are set (safe: llm_completion_span
                # uses start_span, so no ContextVar token detach issue).
                if span_ctx is not None:
                    span_ctx.__exit__(None, None, None)

        return _generator()


class _ChatFacade:
    def __init__(self, registry: LLMProviderRegistry):
        self.completions = _ChatCompletionsFacade(registry)


class _EmbeddingFacade:
    def __init__(self, registry: LLMProviderRegistry):
        self._registry = registry

    def create(
        self,
        *,
        input: str | list[str],
        model: str | None = None,
        **kwargs: Any,
    ) -> Any:
        resolved = self._registry.resolve_embedding(model)
        provider_name = resolved.provider.name
        resolved_model = resolved.model
        started = time.perf_counter()
        with llm_completion_span(
            provider=provider_name,
            model=resolved_model,
            stream=False,
            operation="embedding",
        ) as span:
            try:
                response = resolved.provider.embedding(
                    model=resolved_model,
                    input=input,
                    **kwargs,
                )
            except Exception:
                observe_llm_outcome(
                    operation="embedding",
                    provider=provider_name,
                    model=resolved_model,
                    stream=False,
                    status="error",
                    duration_seconds=time.perf_counter() - started,
                )
                record_llm_usage(span, usage=None, cost_usd=None, status="error")
                raise

            usage = _extract_usage(response)
            status = "success" if usage is not None else "usage_missing"
            cost_usd = (
                estimate_cost_usd(
                    provider=provider_name,
                    model=resolved_model,
                    usage=usage,
                    operation="embedding",
                )
                if usage is not None
                else None
            )
            observe_llm_outcome(
                operation="embedding",
                provider=provider_name,
                model=resolved_model,
                stream=False,
                status=status,
                duration_seconds=time.perf_counter() - started,
                usage=usage,
                cost_usd=cost_usd,
            )
            record_llm_usage(span, usage=usage, cost_usd=cost_usd, status=status)
            return response


class LLMClient:
    """Compatibility client with `.chat.completions.create` and `.embeddings.create`."""

    def __init__(self, registry: LLMProviderRegistry):
        self.chat = _ChatFacade(registry)
        self.embeddings = _EmbeddingFacade(registry)
        self.chat_provider = "dynamic"
        self.embedding_provider = "dynamic"
