# OpenRouter Provider — Design

**Date:** 2026-06-20
**Status:** Approved (design), pending implementation plan

## Goal

Add [OpenRouter](https://openrouter.ai/) as a new LLM provider alongside the
existing OpenAI, Anthropic (claude), Gemini, Grok (xai), and Ollama providers.
OpenRouter is a unified gateway that proxies many vendors' models behind a single
API key, addressed as `openrouter/<vendor>/<model>` (e.g.
`openrouter/deepseek/deepseek-v4-flash`).

**Target model:** DeepSeek V4 Flash, OpenRouter slug `deepseek/deepseek-v4-flash`
— set via `ORCHESTRATOR_MODEL=openrouter/deepseek/deepseek-v4-flash`.

LiteLLM — which already backs every provider in this codebase — supports
OpenRouter natively via the `openrouter/` model prefix and reads
`OPENROUTER_API_KEY` from the environment. No new client library is needed.

## Scope

**Provider parity only.** OpenRouter is wired exactly like the other providers:
selectable by model string and env var (e.g. `ORCHESTRATOR_MODEL`,
agent/embedding model env vars). There is **no** model-picker UI in the app
today and this feature does not introduce one. No changes to the frontend,
`client.py`, services, agents, or prompts.

## Current architecture (context)

The provider layer is a thin abstraction over LiteLLM:

- `llm/base.py` — `BaseLLMProvider` contract (`chat_completion` + `embedding`).
- `llm/providers/litellm_provider.py` — `LiteLLMProvider`, the shared engine.
  Holds a `model_prefix` per provider, normalizes kwargs, sets
  `litellm.drop_params = True`, and routes to `litellm.completion` /
  `litellm.embedding`. `_prefix_model()` prepends `<model_prefix>/` **only if the
  model does not already contain a `/`**.
- `llm/providers/*.py` — each concrete provider is a ~15-line subclass setting
  `name`, `model_prefix`, `default_chat_model`, `default_embedding_model`.
- `llm/providers/__init__.py` — `PROVIDER_BUILDERS` registry dict.
- `llm/factory.py` — `PROVIDER_ALIASES`, `_split_provider_prefix` (splits the
  first `/` segment off and maps it to a provider), `_infer_provider_from_model`
  (used only when no prefix is present), and the `LLMProviderRegistry`.

Model selection is env/string driven; the factory routes a model string to a
provider and the provider hands the final model name to LiteLLM.

## Design

### The key wrinkle: nested slashes

OpenRouter model IDs themselves contain a slash (`deepseek/deepseek-v4-flash`,
`meta-llama/llama-3.1-70b`). The existing flow breaks on this:

1. `factory._split_provider_prefix("openrouter/deepseek/deepseek-v4-flash")`
   splits on the **first** `/` → provider `openrouter`, remainder
   `deepseek/deepseek-v4-flash`.
2. The provider's `_prefix_model("deepseek/deepseek-v4-flash")` sees an existing
   `/` and returns it **unchanged**, dropping the `openrouter/` prefix.
3. LiteLLM receives `deepseek/deepseek-v4-flash` and misroutes it to DeepSeek
   directly (or fails) instead of OpenRouter.

**Fix:** `OpenRouterProvider` overrides `_prefix_model` to always ensure the
`openrouter/` prefix regardless of inner slashes.

### 1. New provider — `llm/providers/openrouter_provider.py`

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
        # OpenRouter model ids contain their own '/' (e.g. anthropic/claude-3.5-sonnet),
        # so the base class's "skip prefixing when a slash is present" logic would
        # drop the openrouter/ prefix and misroute. Always ensure it.
        if model.startswith(f"{self.model_prefix}/"):
            return model
        return f"{self.model_prefix}/{model}"
```

### 2. Register — `llm/providers/__init__.py`

Import `OpenRouterProvider` and add `"openrouter": OpenRouterProvider` to
`PROVIDER_BUILDERS`.

### 3. Factory aliases — `llm/factory.py`

Add to `PROVIDER_ALIASES`:

```python
"openrouter": "openrouter",
"or": "openrouter",
```

No change to `_infer_provider_from_model`: OpenRouter is **only** reachable via an
explicit `openrouter/...` prefix. Inferring it from a bare `vendor/model` string
would collide with the real first-party providers, so we deliberately require the
prefix.

### 4. Config — `.env.example`

Add alongside the other provider keys:

```
OPENROUTER_API_KEY=your_openrouter_api_key
```

LiteLLM reads this automatically. Optional attribution headers
(`OR_SITE_URL` / `OR_APP_NAME`) are **out of scope** unless requested later.

### 5. Tests

Mirror the existing provider tests:

- `openrouter/deepseek/deepseek-v4-flash` resolves to `OpenRouterProvider` and
  the model passed to LiteLLM **keeps** the `openrouter/` prefix (the nested-slash
  regression case — the real target model).
- bare `openrouter` (or `or`) with no model → `openrouter/auto`.
- A single-segment OpenRouter model (`openrouter/auto`) round-trips correctly.

## Data flow (unchanged)

```
ORCHESTRATOR_MODEL=openrouter/deepseek/deepseek-v4-flash
  -> factory.resolve_chat() splits "openrouter/" -> OpenRouterProvider
  -> OpenRouterProvider._prefix_model() re-adds prefix
  -> litellm.completion(model="openrouter/deepseek/deepseek-v4-flash", ...)
  -> OpenRouter gateway -> DeepSeek
```

No changes to `llm/client.py`, services, agents, prompts, or the frontend.

## Decisions worth a second look

- **Default model = `openrouter/auto`** — used only when someone passes a bare
  `openrouter` provider with no model. `auto` is OpenRouter's own routing model,
  so it won't pin to a model that may later be deprecated. Alternative: pin a
  concrete model.
- **No inference rule** — OpenRouter must be addressed with the explicit prefix.

## Out of scope

- Frontend model-picker UI.
- OpenRouter embeddings (the gateway is chat-focused).
- Attribution headers (`OR_SITE_URL` / `OR_APP_NAME`).
- Per-provider cost/usage dashboards.
