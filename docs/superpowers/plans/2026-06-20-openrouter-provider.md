# OpenRouter Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add OpenRouter as a 6th LLM provider, usable via `openrouter/<vendor>/<model>` model strings (target model: DeepSeek V4 Flash).

**Architecture:** OpenRouter is a thin `LiteLLMProvider` subclass like every other provider, registered in `PROVIDER_BUILDERS` and aliased in the factory. The one piece of real logic is an overridden `_prefix_model` that always keeps the `openrouter/` prefix, because OpenRouter model IDs contain their own slash (`deepseek/deepseek-v4-flash`) which would otherwise defeat the base class's prefixing.

**Tech Stack:** Python, LiteLLM (already a dependency), pytest.

## Global Constraints

- Provider parity only — no frontend, no changes to `llm/client.py`, services, agents, or prompts.
- OpenRouter is reachable **only** via an explicit `openrouter/...` prefix — no model-name inference rule.
- Tests run with: `uv run pytest`.
- Follow existing provider patterns exactly (see `llm/providers/grok_provider.py`).
- OpenRouter slug for the target model: `deepseek/deepseek-v4-flash` → full string `openrouter/deepseek/deepseek-v4-flash`.

---

### Task 1: OpenRouter provider + registration + factory aliases

**Files:**
- Create: `llm/providers/openrouter_provider.py`
- Modify: `llm/providers/__init__.py`
- Modify: `llm/factory.py` (the `PROVIDER_ALIASES` dict, lines ~14-24)
- Test: `tests/test_openrouter_provider.py`

**Interfaces:**
- Consumes: `LiteLLMProvider` from `llm.providers.litellm_provider` (constructor kwargs `name`, `model_prefix`, `default_chat_model`, `default_embedding_model`); `LiteLLMProvider._resolve_chat_model(requested_model: str | None) -> str` and `_prefix_model(model: str) -> str`; `get_llm_registry()` from `llm.factory` returning an object with `resolve_chat(model: str | None) -> ResolvedModel(provider, model)`.
- Produces: `OpenRouterProvider` class; registry key `"openrouter"` in `PROVIDER_BUILDERS`; factory aliases `"openrouter"` and `"or"`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_openrouter_provider.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_openrouter_provider.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'llm.providers.openrouter_provider'`.

- [ ] **Step 3: Create the provider**

Create `llm/providers/openrouter_provider.py`:

```python
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
```

- [ ] **Step 4: Register the provider**

In `llm/providers/__init__.py`, add the import and registry entry:

```python
"""Provider registry."""

from llm.providers.anthropic_provider import AnthropicProvider
from llm.providers.gemini_provider import GeminiProvider
from llm.providers.grok_provider import GrokProvider
from llm.providers.ollama_provider import OllamaProvider
from llm.providers.openai_provider import OpenAIProvider
from llm.providers.openrouter_provider import OpenRouterProvider

PROVIDER_BUILDERS = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
    "grok": GrokProvider,
    "ollama": OllamaProvider,
    "openrouter": OpenRouterProvider,
}
```

- [ ] **Step 5: Add factory aliases**

In `llm/factory.py`, add two entries to `PROVIDER_ALIASES` (after the `"llama": "ollama",` line):

```python
    "ollama": "ollama",
    "llama": "ollama",
    "openrouter": "openrouter",
    "or": "openrouter",
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_openrouter_provider.py -v`
Expected: PASS (5 passed).

- [ ] **Step 7: Run the full suite to confirm no regressions**

Run: `uv run pytest -q`
Expected: all tests pass (no existing test references provider counts, so nothing should break).

- [ ] **Step 8: Commit**

```bash
git add llm/providers/openrouter_provider.py llm/providers/__init__.py llm/factory.py tests/test_openrouter_provider.py
git commit -m "feat(llm): add OpenRouter provider"
```

---

### Task 2: Document the OpenRouter API key

**Files:**
- Modify: `.env.example` (provider-keys block, around lines 8-11)

**Interfaces:**
- Consumes: nothing (LiteLLM reads `OPENROUTER_API_KEY` from the environment automatically).
- Produces: documented `OPENROUTER_API_KEY` env var.

- [ ] **Step 1: Add the key to `.env.example`**

After the `GROQ_API_KEY=your_groq_api_key` line in `.env.example`, add:

```
OPENROUTER_API_KEY=your_openrouter_api_key
```

- [ ] **Step 2: Verify the addition**

Run: `grep -n OPENROUTER .env.example`
Expected: one line printed — `OPENROUTER_API_KEY=your_openrouter_api_key`.

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "docs: document OPENROUTER_API_KEY"
```

---

## Manual verification (after both tasks)

With a real `OPENROUTER_API_KEY` in `.env`, set `ORCHESTRATOR_MODEL=openrouter/deepseek/deepseek-v4-flash` and run a chat through the orchestrator (`uv run python main.py` or the API). Confirm the response streams from DeepSeek V4 Flash via OpenRouter and no misrouting error occurs.

## Self-Review

- **Spec coverage:** Provider class ✓ (Task 1 Step 3), `_prefix_model` override ✓ (Task 1 Step 3 + tests), registration ✓ (Task 1 Step 4), factory aliases ✓ (Task 1 Step 5), no inference rule ✓ (explicitly not added), `.env.example` key ✓ (Task 2), tests for nested-slash + bare-default ✓ (Task 1 Step 1). All spec sections mapped.
- **Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step shows full content.
- **Type consistency:** `OpenRouterProvider`, `_resolve_chat_model`, `_prefix_model`, `PROVIDER_BUILDERS`, `PROVIDER_ALIASES`, `get_llm_registry`, `resolve_chat`, `ResolvedModel.provider`/`.model`, `provider.name` all match the existing code read during design.
