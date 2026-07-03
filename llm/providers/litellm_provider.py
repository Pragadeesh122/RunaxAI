"""Shared LiteLLM-backed provider implementation."""

from __future__ import annotations

from typing import Any

from llm.base import BaseLLMProvider

try:
    import litellm
    from litellm import completion as litellm_completion
    from litellm import embedding as litellm_embedding
except Exception as e:  # pragma: no cover - import error path
    litellm = None
    litellm_completion = None
    litellm_embedding = None
    _LITELLM_IMPORT_ERROR = e
else:
    _LITELLM_IMPORT_ERROR = None
    # Silently drop provider-rejected params (e.g. gpt-5 doesn't accept
    # temperature=0). Without this, every router call raises
    # UnsupportedParamsError and we silently fall back to "reasoning".
    litellm.drop_params = True


OPENAI_CHAT_MODEL_ALIASES = {
    "gpt-5.4-mini",
    "gpt-4o",
    "gpt-4o-mini",
}
# Providers whose streams honor stream_options={"include_usage": True} so the
# final chunk carries exact provider-billed token counts. litellm.drop_params
# is True above, so an unsupported provider would silently drop the param and
# fall back to tokenizer estimation — never error. Ollama stays out: it
# reports usage in its final chunk without the flag.
STREAM_OPTIONS_ALLOWED_PROVIDERS = {"openai", "grok", "openrouter", "anthropic", "gemini"}

class LiteLLMProvider(BaseLLMProvider):
    """Provider wrapper that normalizes model names + kwargs for LiteLLM."""

    def __init__(
        self,
        *,
        name: str,
        model_prefix: str,
        default_chat_model: str,
        default_embedding_model: str | None = None,
    ) -> None:
        self.name = name
        self.model_prefix = model_prefix
        self.default_chat_model = default_chat_model
        self.default_embedding_model = default_embedding_model

    def _ensure_litellm(self) -> None:
        if litellm_completion is None or litellm_embedding is None:
            raise RuntimeError(
                "litellm is required for multi-provider LLM support. "
                "Install dependencies to continue."
            ) from _LITELLM_IMPORT_ERROR

    def _prefix_model(self, model: str) -> str:
        if "/" in model:
            return model
        return f"{self.model_prefix}/{model}"

    def _resolve_chat_model(self, requested_model: str | None) -> str:
        model = requested_model or self.default_chat_model
        if self.name != "openai" and model in OPENAI_CHAT_MODEL_ALIASES:
            model = self.default_chat_model
        return self._prefix_model(model)

    def _resolve_embedding_model(self, requested_model: str | None) -> str:
        model = requested_model or self.default_embedding_model
        if not model:
            raise RuntimeError(
                f"Provider '{self.name}' has no default embedding model. "
                "Pass model=... explicitly for this provider."
            )
        return self._prefix_model(model)

    def _completion_extra_kwargs(self) -> dict[str, Any]:
        return {}

    def _embedding_extra_kwargs(self) -> dict[str, Any]:
        return {}

    def chat_completion(
        self,
        *,
        model: str | None,
        messages: list[dict],
        stream: bool = False,
        **kwargs: Any,
    ) -> Any:
        self._ensure_litellm()
        call_kwargs = dict(kwargs)
        if "max_completion_tokens" in call_kwargs and "max_tokens" not in call_kwargs:
            call_kwargs["max_tokens"] = call_kwargs.pop("max_completion_tokens")
        if self.name not in STREAM_OPTIONS_ALLOWED_PROVIDERS:
            call_kwargs.pop("stream_options", None)

        model_name = self._resolve_chat_model(model)
        return litellm_completion(
            model=model_name,
            messages=messages,
            stream=stream,
            **self._completion_extra_kwargs(),
            **call_kwargs,
        )

    def embedding(
        self,
        *,
        model: str | None,
        input: str | list[str],
        **kwargs: Any,
    ) -> Any:
        self._ensure_litellm()
        model_name = self._resolve_embedding_model(model)
        return litellm_embedding(
            model=model_name,
            input=input,
            **self._embedding_extra_kwargs(),
            **kwargs,
        )
