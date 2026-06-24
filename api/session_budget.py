"""Per-session spend guardrail.

A cheap, Redis-backed ceiling on cumulative token usage per chat session. This
bounds the blast radius of a runaway loop, an abusive client, or a pathological
conversation: once a session has spent more than the configured token budget it
is refused further turns until it ages out (the counter shares the session TTL).

This complements the per-turn context cap (``MAX_PROMPT_TOKENS`` in the chat
handlers, which triggers summarization). That cap bounds the size of a single
request; this ceiling bounds the cumulative cost of a whole session.

Defaults are intentionally generous so legitimate long research sessions are not
interrupted, while still capping spend at a few dollars per session. Tune via the
``MAX_SESSION_TOKENS`` env var (0 disables enforcement).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from memory.redis_client import redis_client
from observability.metrics import observe_session_budget_blocked

logger = logging.getLogger("session_budget")

# Cumulative prompt+completion tokens allowed per session before turns are
# refused. 2,000,000 tokens is ~/session at GPT-4o-class blended pricing and
# far above any honest single conversation, so it only trips on abuse/runaways.
MAX_SESSION_TOKENS = int(os.getenv("MAX_SESSION_TOKENS", "2000000"))

# Counter key shares the 24h session TTL so it resets when the session ages out.
_SESSION_TTL = 60 * 60 * 24


def _tokens_key(session_id: str) -> str:
    return f"session:{session_id}:tokens"


@dataclass(frozen=True)
class SessionBudgetStatus:
    allowed: bool
    used_tokens: int
    ceiling: int

    @property
    def remaining(self) -> int:
        return max(0, self.ceiling - self.used_tokens)


def _enabled() -> bool:
    return MAX_SESSION_TOKENS > 0


def check_session_budget(session_id: str) -> SessionBudgetStatus:
    """Return whether ``session_id`` is still under its token ceiling.

    Never raises: a Redis failure fails open (allowed) so an observability
    guardrail can never take down the chat path.
    """
    if not _enabled() or not session_id:
        return SessionBudgetStatus(True, 0, MAX_SESSION_TOKENS)
    try:
        raw = redis_client.get(_tokens_key(session_id))
        used = int(raw) if raw else 0
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"session budget check failed, allowing turn: {e}")
        return SessionBudgetStatus(True, 0, MAX_SESSION_TOKENS)
    return SessionBudgetStatus(used < MAX_SESSION_TOKENS, used, MAX_SESSION_TOKENS)


def record_session_tokens(
    session_id: str, prompt_tokens: int, completion_tokens: int
) -> None:
    """Add a turn's token usage to the session's cumulative counter."""
    if not _enabled() or not session_id:
        return
    total = max(0, int(prompt_tokens or 0)) + max(0, int(completion_tokens or 0))
    if total <= 0:
        return
    try:
        key = _tokens_key(session_id)
        new_total = redis_client.incrby(key, total)
        # Keep the counter alive for the session window; refresh on each turn.
        redis_client.expire(key, _SESSION_TTL)
        if new_total >= MAX_SESSION_TOKENS:
            logger.info(
                f"session {session_id} reached token ceiling: "
                f"{new_total}/{MAX_SESSION_TOKENS}"
            )
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"failed to record session tokens: {e}")


def budget_exceeded_message(status: SessionBudgetStatus) -> str:
    return (
        "This conversation has reached its usage limit "
        f"({status.used_tokens:,}/{status.ceiling:,} tokens). "
        "Start a new chat to continue."
    )


def note_session_budget_blocked(*, chat_type: str) -> None:
    """Record the guardrail trip for observability."""
    observe_session_budget_blocked(chat_type=chat_type, limit="session_tokens")
