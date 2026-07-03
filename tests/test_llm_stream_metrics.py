import unittest
from unittest.mock import patch

from llm.client import _ChatCompletionsFacade


class _DummyProvider:
    def __init__(self, name: str, chunks: list[dict]):
        self.name = name
        self._chunks = chunks
        self.calls: list[dict] = []

    def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return iter(self._chunks)


class _Resolved:
    def __init__(self, provider, model: str):
        self.provider = provider
        self.model = model


class _Registry:
    def __init__(self, provider, model: str):
        self._provider = provider
        self._model = model

    def resolve_chat(self, _model):
        return _Resolved(self._provider, self._model)


class LLMStreamInstrumentationTests(unittest.TestCase):
    @patch("llm.client.estimate_cost_usd", return_value=0.002)
    @patch("llm.client.observe_llm_output_speed")
    @patch("llm.client.observe_llm_outcome")
    @patch("llm.client.observe_llm_ttft")
    def test_openai_stream_emits_ttft_and_final_usage(
        self,
        ttft_mock,
        outcome_mock,
        speed_mock,
        _cost_mock,
    ):
        chunks = [
            {"choices": [{"delta": {"content": "Hello"}}]},
            {
                "choices": [{"delta": {}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            },
        ]
        provider = _DummyProvider("openai", chunks)
        facade = _ChatCompletionsFacade(_Registry(provider, "gpt-5.4-mini"))

        stream = facade.create(messages=[{"role": "user", "content": "hi"}], stream=True)
        list(stream)

        self.assertEqual(provider.calls[0]["stream_options"], {"include_usage": True})
        ttft_mock.assert_called_once()
        speed_mock.assert_called_once()
        outcome_mock.assert_called_once()
        self.assertEqual(outcome_mock.call_args.kwargs["status"], "success")
        self.assertTrue(outcome_mock.call_args.kwargs["stream"])
        self.assertEqual(
            outcome_mock.call_args.kwargs["usage"],
            {"prompt_tokens": 11, "completion_tokens": 7},
        )

    @patch("llm.client.estimate_cost_usd", return_value=0.002)
    @patch("llm.client.observe_llm_output_speed")
    @patch("llm.client.observe_llm_outcome")
    @patch("llm.client.observe_llm_ttft")
    def test_stream_usage_providers_request_and_capture_exact_usage(
        self,
        _ttft_mock,
        outcome_mock,
        _speed_mock,
        _cost_mock,
    ):
        # openrouter is prod's orchestrator gateway; anthropic/gemini stream
        # usage through litellm the same way. All three must request
        # include_usage and record provider-exact counts, not estimates.
        for provider_name, model in (
            ("openrouter", "openrouter/deepseek/deepseek-v4-flash"),
            ("anthropic", "claude-haiku-4-5"),
            ("gemini", "gemini-3-flash-preview"),
        ):
            with self.subTest(provider=provider_name):
                outcome_mock.reset_mock()
                chunks = [
                    {"choices": [{"delta": {"content": "Hello"}}]},
                    {
                        "choices": [{"delta": {}}],
                        "usage": {"prompt_tokens": 21, "completion_tokens": 9},
                    },
                ]
                provider = _DummyProvider(provider_name, chunks)
                facade = _ChatCompletionsFacade(_Registry(provider, model))

                stream = facade.create(
                    messages=[{"role": "user", "content": "hi"}], stream=True
                )
                list(stream)

                self.assertEqual(
                    provider.calls[0]["stream_options"], {"include_usage": True}
                )
                self.assertEqual(
                    outcome_mock.call_args.kwargs["status"], "success"
                )
                self.assertEqual(
                    outcome_mock.call_args.kwargs["usage"],
                    {"prompt_tokens": 21, "completion_tokens": 9},
                )

    @patch("llm.client.estimate_cost_usd", return_value=None)
    @patch("llm.client._estimate_usage", return_value=None)
    @patch("llm.client.observe_llm_output_speed")
    @patch("llm.client.observe_llm_outcome")
    @patch("llm.client.observe_llm_ttft")
    def test_non_supported_provider_skips_stream_options_and_handles_usage_missing(
        self,
        ttft_mock,
        outcome_mock,
        speed_mock,
        _estimate_usage_mock,
        _cost_mock,
    ):
        chunks = [
            {"choices": [{"delta": {"content": "Hello"}}]},
            {"choices": [{"delta": {}}]},
        ]
        provider = _DummyProvider("ollama", chunks)
        facade = _ChatCompletionsFacade(_Registry(provider, "llama3.1"))

        stream = facade.create(
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        )
        list(stream)

        self.assertNotIn("stream_options", provider.calls[0])
        ttft_mock.assert_called_once()
        speed_mock.assert_not_called()
        outcome_mock.assert_called_once()
        self.assertEqual(outcome_mock.call_args.kwargs["status"], "usage_missing")
        self.assertIsNone(outcome_mock.call_args.kwargs["usage"])

    @patch("llm.client.estimate_cost_usd", return_value=0.001)
    @patch(
        "llm.client._estimate_usage",
        return_value={"prompt_tokens": 13, "completion_tokens": 5},
    )
    @patch("llm.client.observe_llm_output_speed")
    @patch("llm.client.observe_llm_outcome")
    @patch("llm.client.observe_llm_ttft")
    def test_stream_usage_is_estimated_when_provider_omits_usage(
        self,
        ttft_mock,
        outcome_mock,
        speed_mock,
        _estimate_usage_mock,
        _cost_mock,
    ):
        chunks = [
            {"choices": [{"delta": {"content": "Hello"}}]},
            {"choices": [{"delta": {}}]},
        ]
        provider = _DummyProvider("ollama", chunks)
        facade = _ChatCompletionsFacade(_Registry(provider, "llama3.1"))

        stream = facade.create(
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        )
        list(stream)

        outcome_mock.assert_called_once()
        self.assertEqual(outcome_mock.call_args.kwargs["status"], "usage_estimated")
        self.assertEqual(
            outcome_mock.call_args.kwargs["usage"],
            {"prompt_tokens": 13, "completion_tokens": 5},
        )
        ttft_mock.assert_called_once()
        speed_mock.assert_called_once()
