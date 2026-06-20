"""Agent router — classifies user intent and selects the appropriate agent."""

import logging
import time
from clients import llm_client
from agents.registry import AGENTS
from agents.base import Agent
from llm.factory import get_orchestrator_model
from llm.response_utils import extract_first_text
from observability.context import set_agent_name
from observability.metrics import observe_agent_route
from observability.spans import agent_route_span as _agent_route_span, classify_intent_span

logger = logging.getLogger("agents.router")

CLASSIFICATION_PROMPT = """\
You are an intent classifier for a document Q&A system. Pick exactly one agent \
that should handle the user's LATEST message, based on the full conversation.

Agents (mutually exclusive — pick the single best match):
- reasoning: Default. Deep Q&A, explanations, multi-hop analysis, comparisons in prose, \
  follow-up discussion, "what / why / how / which / does / is" style questions, \
  and anything that needs web/external lookup.
- quiz: User explicitly asks for a quiz, flashcards, test questions, MCQs, or "quiz me".
- visualization: User asks for a chart, graph, diagram, flowchart, mindmap, timeline, \
  table, mermaid, "visualize", "draw", "plot", "show me a diagram".
- summary: User asks for a summary, TL;DR, overview, key takeaways, "summarize this".

Disambiguation rules:
- "Compare X and Y in detail" → reasoning. "Compare X and Y as a chart/table" → visualization.
- "List the key points" → summary. "Explain the key points" → reasoning.
- "Make 5 questions" / "test me" → quiz, even without the word "quiz".
- "Give me a flowchart of …" / "draw …" → visualization, even without the word "chart".
- Continuation cues ("one more", "again", "next", "another one", "do that for X too") \
  keep the SAME agent as the previous assistant turn.
- If the user explicitly requests a different format ("now show as a chart", "make this \
  a quiz instead"), SWITCH to that agent.
- If the message is ambiguous or conversational ("ok thanks", "yes", "hmm"), keep the \
  previous agent; if no previous agent exists, return reasoning.

Output format:
- Respond with EXACTLY one lowercase word: reasoning | quiz | visualization | summary
- No punctuation, no quotes, no explanation.\
"""

_VALID_AGENT_NAMES = {"reasoning", "quiz", "visualization", "summary"}


def _normalize_classification(raw: str) -> str:
    """Strip punctuation/quoting/whitespace so models that output `"quiz."` still match."""
    cleaned = raw.strip().lower().strip("\"'`. ,\n\t")
    # Keep only the first token in case the model adds explanation
    cleaned = cleaned.split()[0] if cleaned else ""
    return cleaned


def classify_intent(messages: list[dict]) -> tuple[str, str]:
    """Classify intent from the full conversation."""
    with classify_intent_span():
        try:
            classification_messages = [{"role": "system", "content": CLASSIFICATION_PROMPT}]

            # Pass the full conversation (skip system prompt)
            for msg in messages:
                if msg["role"] in ("user", "assistant"):
                    classification_messages.append({
                        "role": msg["role"],
                        "content": msg["content"][:300],
                    })

            # NOTE: do NOT pass temperature here. gpt-5* models reject any
            # value other than the default (1) and litellm raises
            # UnsupportedParamsError. The classifier prompt + max_tokens=10
            # already keep the output deterministic in practice.
            response = llm_client.chat.completions.create(
                model=get_orchestrator_model(),
                messages=classification_messages,
                max_completion_tokens=10,
            )
            raw = extract_first_text(response, "")
            agent_name = _normalize_classification(raw)

            if agent_name in AGENTS and agent_name in _VALID_AGENT_NAMES:
                logger.info(f"classified intent → {agent_name}")
                return agent_name, "success"

            logger.warning(
                f"unknown agent '{raw!r}' (normalized '{agent_name}'), falling back to reasoning"
            )
            return "reasoning", "fallback"

        except Exception as e:
            logger.error(f"intent classification failed: {e}")
            return "reasoning", "error"


def route(user_message: str, agent_name: str | None, messages: list[dict]) -> Agent:
    """Route to an agent — explicit name or auto-classify from conversation."""
    started = time.perf_counter()
    if agent_name and agent_name != "auto" and agent_name in AGENTS:
        with _agent_route_span(route_mode="explicit") as span:
            observe_agent_route(
                selected_agent=agent_name,
                route_mode="explicit",
                status="success",
                duration_seconds=time.perf_counter() - started,
            )
            if span is not None:
                span.set_attribute("selected_agent", agent_name)
                span.set_attribute("status", "success")
            set_agent_name(agent_name)
            return AGENTS[agent_name]

    # Auto: classify from full conversation + new message
    with _agent_route_span(route_mode="auto") as span:
        classify_msgs = messages + [{"role": "user", "content": user_message}]
        classified, status = classify_intent(classify_msgs)
        observe_agent_route(
            selected_agent=classified,
            route_mode="auto",
            status=status,
            duration_seconds=time.perf_counter() - started,
        )
        if span is not None:
            span.set_attribute("selected_agent", classified)
            span.set_attribute("status", status)
        set_agent_name(classified)
        return AGENTS[classified]
