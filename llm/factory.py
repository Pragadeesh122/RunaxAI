"""Factory and model-resolution helpers for provider-agnostic LLM calls."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from llm.base import BaseLLMProvider
from llm.providers import PROVIDER_BUILDERS

DEFAULT_CHAT_MODEL = "openai/gpt-5.4-mini"
DEFAULT_EMBEDDING_MODEL = "openai/text-embedding-3-large"

PROVIDER_ALIASES = {
    "openai": "openai",
    "anthropic": "anthropic",
    "claude": "anthropic",
    "gemini": "gemini",
    "google": "gemini",
    "grok": "grok",
    "xai": "grok",
    "ollama": "ollama",
    "llama": "ollama",
    "openrouter": "openrouter",
    "or": "openrouter",
}

OLLAMA_MODEL_HINTS = (
    "llama",
    "mistral",
    "qwen",
    "phi",
    "gemma",
    "deepseek",
)


def _normalize_provider_name(name: str) -> str:
    provider = PROVIDER_ALIASES.get(name.strip().lower(), name.strip().lower())
    if provider not in PROVIDER_BUILDERS:
        supported = ", ".join(sorted(PROVIDER_BUILDERS))
        raise ValueError(f"Unsupported provider '{name}'. Supported: {supported}")
    return provider


def _split_provider_prefix(model: str) -> tuple[str | None, str]:
    if "/" not in model:
        return None, model
    provider_hint, remainder = model.split("/", 1)
    if not remainder:
        return None, model
    try:
        return _normalize_provider_name(provider_hint), remainder
    except ValueError:
        return None, model


def _infer_provider_from_model(model: str) -> str:
    lower = model.lower().strip()
    if lower.startswith("claude"):
        return "anthropic"
    if lower.startswith("gemini"):
        return "gemini"
    if lower.startswith("grok"):
        return "grok"
    if lower.startswith("text-embedding-004"):
        return "gemini"
    if lower.startswith("text-embedding-"):
        return "openai"
    if ":" in lower or lower.startswith(OLLAMA_MODEL_HINTS):
        return "ollama"
    return "openai"


@dataclass(frozen=True)
class ResolvedModel:
    provider: BaseLLMProvider
    model: str


class LLMProviderRegistry:
    def __init__(self) -> None:
        self._providers = {
            name: builder() for name, builder in PROVIDER_BUILDERS.items()
        }

    def get_provider(self, name: str) -> BaseLLMProvider:
        return self._providers[_normalize_provider_name(name)]

    def resolve_chat(self, model: str | None) -> ResolvedModel:
        requested = (model or DEFAULT_CHAT_MODEL).strip()
        provider_name, provider_model = _split_provider_prefix(requested)
        if provider_name is None:
            provider_name = _infer_provider_from_model(requested)
            provider_model = requested
        return ResolvedModel(
            provider=self.get_provider(provider_name),
            model=provider_model,
        )

    def resolve_embedding(self, model: str | None) -> ResolvedModel:
        requested = (model or DEFAULT_EMBEDDING_MODEL).strip()
        provider_name, provider_model = _split_provider_prefix(requested)
        if provider_name is None:
            provider_name = _infer_provider_from_model(requested)
            provider_model = requested
        return ResolvedModel(
            provider=self.get_provider(provider_name),
            model=provider_model,
        )


@lru_cache(maxsize=1)
def get_llm_registry() -> LLMProviderRegistry:
    return LLMProviderRegistry()
