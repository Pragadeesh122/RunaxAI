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

