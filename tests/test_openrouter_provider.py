"""Tests for the OpenRouter provider and its factory wiring."""

from llm.factory import get_llm_registry
from llm.providers.openrouter_provider import OpenRouterProvider


def test_prefix_preserved_for_nested_slash_model():
    """OpenRouter model ids contain their own slash; the openrouter/ prefix
    must survive so LiteLLM routes to OpenRouter, not the inner vendor."""
    provider = OpenRouterProvider()
    assert (
        provider._resolve_chat_model("deepseek/deepseek-v4-flash")
        == "openrouter/deepseek/deepseek-v4-flash"
    )


def test_already_prefixed_model_not_double_prefixed():
    provider = OpenRouterProvider()
    assert (
        provider._resolve_chat_model("openrouter/deepseek/deepseek-v4-flash")
        == "openrouter/deepseek/deepseek-v4-flash"
    )


def test_bare_default_model_resolves_to_auto():
    provider = OpenRouterProvider()
    assert provider._resolve_chat_model(None) == "openrouter/auto"


def test_registry_routes_openrouter_prefix_to_provider():
    resolved = get_llm_registry().resolve_chat("openrouter/deepseek/deepseek-v4-flash")
    assert resolved.provider.name == "openrouter"
    # factory strips the leading "openrouter/" segment; provider re-adds it later
    assert resolved.model == "deepseek/deepseek-v4-flash"


def test_or_alias_routes_to_openrouter():
    resolved = get_llm_registry().resolve_chat("or/deepseek/deepseek-v4-flash")
    assert resolved.provider.name == "openrouter"
