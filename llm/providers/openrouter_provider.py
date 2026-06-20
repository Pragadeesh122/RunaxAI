"""OpenRouter unified-gateway provider adapter."""

from __future__ import annotations

from llm.providers.litellm_provider import LiteLLMProvider


class OpenRouterProvider(LiteLLMProvider):
    def __init__(self) -> None:
        super().__init__(
            name="openrouter",
            model_prefix="openrouter",
            default_chat_model="auto",        # -> openrouter/auto (OpenRouter's own router)
            default_embedding_model=None,     # OpenRouter is chat-only
        )

    def _prefix_model(self, model: str) -> str:
        # OpenRouter model ids carry their own '/' (e.g. deepseek/deepseek-v4-flash),
        # so the base class's "skip prefixing when a slash is present" rule would drop
        # the openrouter/ prefix and misroute. Always ensure the prefix.
        if model.startswith(f"{self.model_prefix}/"):
            return model
        return f"{self.model_prefix}/{model}"
