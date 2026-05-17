"""Contract tests for the memory extraction prompt.

We don't try to evaluate LLM behaviour here — that needs an end-to-end eval.
Instead these lock in the wording that fixes follow-up #4: the extractor must
permit user confirmation/selection of an assistant proposal as a valid source
of fact substance, while still rejecting raw assistant opinions and polite
acknowledgements.
"""

from __future__ import annotations

from prompts.memory import MEMORY_EXTRACTION


def test_extraction_prompt_permits_confirmation_of_assistant_proposal():
    """If this assertion fails the prompt has reverted to forbidding all
    assistant-sourced substance, which drops most real-world confirmation
    patterns ('FastAPI', 'go with B', 'the second one').
    """
    assert "selects or confirms" in MEMORY_EXTRACTION, (
        "extraction prompt no longer permits user confirmation of an "
        "assistant proposal as a fact source"
    )
    assert "Confirmation patterns TO extract" in MEMORY_EXTRACTION, (
        "extraction prompt is missing the positive confirmation few-shot"
    )


def test_extraction_prompt_rejects_polite_acknowledgements():
    """The flip side: 'thanks' / 'ok' / 'got it' must not turn the assistant's
    recommendation into a user fact. Without this guard rail loosening the
    confirmation rule causes false positives.
    """
    assert "polite acknowledgement" in MEMORY_EXTRACTION or (
        "polite acknowledgment" in MEMORY_EXTRACTION
    ), "extraction prompt is missing the polite-ack negative example"
    assert "extract nothing" in MEMORY_EXTRACTION, (
        "extraction prompt is missing an explicit 'extract nothing' example"
    )


def test_extraction_prompt_still_forbids_raw_assistant_opinions():
    """The original constraint that assistant opinions are not user facts must
    survive the loosening.
    """
    assert "Never extract the assistant's opinions" in MEMORY_EXTRACTION, (
        "extraction prompt no longer explicitly excludes assistant opinions"
    )
