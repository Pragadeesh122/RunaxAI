"""Tests for the single-source orchestrator model resolver."""

from llm import factory


def test_orchestrator_model_from_env(monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_MODEL", "openrouter/deepseek/deepseek-v4-flash")
    assert (
        factory.get_orchestrator_model() == "openrouter/deepseek/deepseek-v4-flash"
    )


def test_orchestrator_model_default_when_unset(monkeypatch):
    monkeypatch.delenv("ORCHESTRATOR_MODEL", raising=False)
    assert factory.get_orchestrator_model() == factory.DEFAULT_ORCHESTRATOR_MODEL


def test_orchestrator_model_blank_env_falls_back_to_default(monkeypatch):
    # A blank env var (e.g. an unset Helm value rendered as "") must not blank
    # out the model — it must fall back to the code default.
    monkeypatch.setenv("ORCHESTRATOR_MODEL", "   ")
    assert factory.get_orchestrator_model() == factory.DEFAULT_ORCHESTRATOR_MODEL
