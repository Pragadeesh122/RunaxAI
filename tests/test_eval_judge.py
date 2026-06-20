"""Unit tests for evals/judge.py — judge response parsing and fallback.

These are pure/offline: the LLM client is faked so no network or API key is
required. They guard the parsing logic that turns a judge's raw text into
structured scores, which is the part most likely to silently break.
"""

from evals.judge import _parse_judge_response, judge_answer, EXPECTED_DIMENSIONS


def _valid_payload() -> dict:
    return {
        "faithfulness": {"score": 5, "reason": "grounded"},
        "completeness": {"score": 4, "reason": "minor gap"},
        "hallucination": {"score": 5, "reason": "no unsupported claims"},
        "format_adherence": {"score": 5, "reason": "prose as expected"},
    }


# --- _parse_judge_response ---

def test_parse_raw_json():
    import json
    parsed = _parse_judge_response(json.dumps(_valid_payload()))
    assert parsed is not None
    assert EXPECTED_DIMENSIONS <= set(parsed)
    assert parsed["faithfulness"]["score"] == 5


def test_parse_json_in_code_fence():
    import json
    text = "Here is my evaluation:\n```json\n" + json.dumps(_valid_payload()) + "\n```\n"
    parsed = _parse_judge_response(text)
    assert parsed is not None
    assert parsed["completeness"]["score"] == 4


def test_parse_json_in_bare_fence():
    import json
    text = "```\n" + json.dumps(_valid_payload()) + "\n```"
    parsed = _parse_judge_response(text)
    assert parsed is not None
    assert EXPECTED_DIMENSIONS <= set(parsed)


def test_parse_json_with_surrounding_prose():
    import json
    text = "Sure! " + json.dumps(_valid_payload()) + " Hope that helps."
    parsed = _parse_judge_response(text)
    assert parsed is not None
    assert parsed["hallucination"]["score"] == 5


def test_parse_missing_dimension_returns_none():
    import json
    payload = _valid_payload()
    del payload["format_adherence"]
    assert _parse_judge_response(json.dumps(payload)) is None


def test_parse_garbage_returns_none():
    assert _parse_judge_response("not json at all") is None


def test_parse_empty_returns_none():
    assert _parse_judge_response("") is None


# --- judge_answer with a fake client ---

class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, content=None, raise_exc=False):
        self._content = content
        self._raise = raise_exc
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self._raise:
            raise RuntimeError("simulated API failure")
        return _FakeResponse(self._content)


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeLLMClient:
    def __init__(self, content=None, raise_exc=False):
        self.chat = _FakeChat(_FakeCompletions(content, raise_exc))


def test_judge_answer_parses_valid_response():
    import json
    client = _FakeLLMClient(content=json.dumps(_valid_payload()))
    scores = judge_answer(
        query="q",
        answer="a",
        retrieved_chunks=["chunk"],
        expected_traits={"must_mention": ["x"]},
        llm_client=client,
        max_retries=0,
    )
    assert scores["faithfulness"]["score"] == 5
    assert EXPECTED_DIMENSIONS <= set(scores)


def test_judge_answer_falls_back_to_zeros_on_failure():
    client = _FakeLLMClient(raise_exc=True)
    scores = judge_answer(
        query="q",
        answer="a",
        retrieved_chunks=[],
        expected_traits={},
        llm_client=client,
        max_retries=1,
    )
    assert EXPECTED_DIMENSIONS <= set(scores)
    for dim in EXPECTED_DIMENSIONS:
        assert scores[dim]["score"] == 0
        assert scores[dim]["reason"] == "judge_failed"
    # 1 initial attempt + 1 retry
    assert client.chat.completions.calls == 2


def test_judge_answer_retries_on_malformed_then_zeros():
    client = _FakeLLMClient(content="totally not json")
    scores = judge_answer(
        query="q",
        answer="a",
        retrieved_chunks=[],
        expected_traits={},
        llm_client=client,
        max_retries=2,
    )
    for dim in EXPECTED_DIMENSIONS:
        assert scores[dim]["score"] == 0
    assert client.chat.completions.calls == 3
