import json
import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest

from memory import semantic


class _FakeSyncSession:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.executed = []
        self.added = []
        self.committed = False

    def execute(self, stmt, params=None):
        self.executed.append((str(stmt), params))
        return SimpleNamespace(
            fetchall=lambda: self.rows,
            first=lambda: self.rows[0] if self.rows else None,
        )

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        for idx, obj in enumerate(self.added, start=1):
            if getattr(obj, "id", None) is None:
                obj.id = f"fact-{idx}"

    def commit(self):
        self.committed = True


class _SessionFactory:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc, tb):
        return False


def test_extract_candidate_facts_uses_observation_date_and_summary(monkeypatch):
    captured = {}

    def fake_create(**kwargs):
        captured["messages"] = kwargs["messages"]
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "facts": [
                                    "Builds AgenticRag with FastAPI",
                                    "Prefers concise explanations",
                                ]
                            }
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(
        semantic,
        "llm_client",
        SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=fake_create)
            )
        ),
    )

    facts = semantic._extract_candidate_facts(
        messages=[
            {"role": "assistant", "content": "Which framework did you choose?"},
            {"role": "user", "content": "I went with FastAPI for AgenticRag."},
        ],
        rolling_summary="The user is refining the AgenticRag backend.",
        observation_date=datetime(2026, 4, 15),
    )

    assert facts == [
        "Builds AgenticRag with FastAPI",
        "Prefers concise explanations",
    ]
    user_payload = captured["messages"][1]["content"]
    assert "Observation Date: 2026-04-15" in user_payload
    assert "Rolling summary of this session so far:" in user_payload
    assert "assistant: Which framework did you choose?" in user_payload
    assert "user: I went with FastAPI for AgenticRag." in user_payload


def test_extract_passes_response_format_json_object(monkeypatch):
    """The extractor must request JSON mode so the model doesn't wrap output in
    markdown fences. Without this, parsing fails silently and we lose every
    candidate fact from the conversation.
    """
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return {
            "choices": [
                {"message": {"content": json.dumps({"facts": []})}}
            ]
        }

    monkeypatch.setattr(
        semantic,
        "llm_client",
        SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=fake_create)
            )
        ),
    )

    semantic._extract_candidate_facts(
        messages=[{"role": "user", "content": "I use FastAPI."}],
        rolling_summary=None,
        observation_date=datetime(2026, 4, 15),
    )

    assert captured.get("response_format") == {"type": "json_object"}, (
        "extractor LLM call is missing response_format={'type':'json_object'} "
        "— without it the model often returns markdown-fenced JSON which "
        "json.loads cannot parse, and _extract_candidate_facts returns []."
    )


def test_extract_handles_markdown_fenced_json(monkeypatch):
    """Simulates the real-world failure mode: model returns its JSON wrapped in
    ```json ... ``` fences (which is what happens when response_format isn't
    set). The extractor must still recover the facts — today it returns [].
    """
    fenced_payload = (
        "```json\n"
        + json.dumps({"facts": ["Builds AgenticRag with FastAPI"]})
        + "\n```"
    )

    def fake_create(**kwargs):
        return {"choices": [{"message": {"content": fenced_payload}}]}

    monkeypatch.setattr(
        semantic,
        "llm_client",
        SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=fake_create)
            )
        ),
    )

    facts = semantic._extract_candidate_facts(
        messages=[{"role": "user", "content": "I built AgenticRag with FastAPI."}],
        rolling_summary=None,
        observation_date=datetime(2026, 4, 15),
    )

    assert facts == ["Builds AgenticRag with FastAPI"], (
        "Extractor swallowed a markdown-fenced JSON response and dropped "
        "every candidate fact. This is the root cause of empty memory in UI."
    )


def test_extract_raises_on_unrecoverable_parse_failure(monkeypatch):
    """If the model returns content that survives neither json.loads nor the
    fenced-fallback, the extractor must raise — NOT return [] — so that the
    ARQ task can refuse to advance its cursor and the messages get retried.
    """
    def fake_create(**kwargs):
        return {"choices": [{"message": {"content": "not json at all, sorry"}}]}

    monkeypatch.setattr(
        semantic,
        "llm_client",
        SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=fake_create)
            )
        ),
    )

    with pytest.raises(semantic.MemoryExtractionError):
        semantic._extract_candidate_facts(
            messages=[{"role": "user", "content": "I built it with FastAPI."}],
            rolling_summary=None,
            observation_date=datetime(2026, 4, 15),
        )


def test_consolidate_raises_on_unrecoverable_parse_failure(monkeypatch):
    """Same protection for the consolidation pass — silently returning all-NONE
    on a parse failure means the writes never happen and the cursor advances
    anyway.
    """
    def fake_create(**kwargs):
        return {"choices": [{"message": {"content": "definitely not json"}}]}

    monkeypatch.setattr(
        semantic,
        "llm_client",
        SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=fake_create)
            )
        ),
    )

    with pytest.raises(semantic.MemoryExtractionError):
        semantic._consolidate_batch(
            ["Works at Acme"],
            {0: []},
        )


def test_consolidate_batch_defaults_missing_decisions_to_none(monkeypatch):
    def fake_create(**kwargs):
        messages = kwargs["messages"]
        assert "candidate_index=0" in messages[1]["content"]
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "decisions": [
                                    {
                                        "candidate_index": 0,
                                        "action": "UPDATE",
                                        "supersedes_id": "fact-1",
                                    }
                                ]
                            }
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(
        semantic,
        "llm_client",
        SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=fake_create)
            )
        ),
    )

    decisions = semantic._consolidate_batch(
        ["Works at Acme", "Prefers concise answers"],
        {
            0: [SimpleNamespace(id="fact-1", text="Works at Beta")],
            1: [SimpleNamespace(id="fact-2", text="Prefers concise answers")],
        },
    )

    assert decisions == [
        {"candidate_index": 0, "action": "UPDATE", "supersedes_id": "fact-1"},
        {"candidate_index": 1, "action": "NONE"},
    ]


def test_get_user_memory_formats_unsuperseded_facts(monkeypatch):
    session = _FakeSyncSession(
        rows=[("Builds AgenticRag with FastAPI",), ("Prefers concise answers",)]
    )
    monkeypatch.setattr(semantic, "sync_session_maker", _SessionFactory(session))

    user_id = str(uuid.uuid4())
    memory = semantic.get_user_memory(user_id)

    assert memory == (
        "- Builds AgenticRag with FastAPI\n"
        "- Prefers concise answers"
    )
    assert "superseded_at IS NULL" in session.executed[0][0]
    assert session.executed[0][1]["uid"] == user_id
