"""ARQ task: extract memory from a conversation slice.

Cursor strategy
---------------
We advance a per-session cursor keyed on the SHA-256 of the last message's
content (not an index — indexes break when ``summarize_messages`` collapses the
array). On each run:

1. If no cursor exists → extract the full conversation. This is the first run
   for this session or the cursor was explicitly invalidated after a
   summarization event.
2. If the cursor hash is found in the current message list → extract only the
   messages *after* that index.
3. If the cursor hash is NOT found (the message was collapsed into a summary)
   → extract the whole current conversation; the rolling summary gives the
   extractor enough context to attribute short replies.

After successful extraction we store the SHA-256 of the last message as the new
cursor and refresh the rolling summary every ``ROLLING_SUMMARY_EVERY`` user turns.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Optional

from memory.redis_client import redis_client
from memory.semantic import (
    MemoryExtractionError,
    extract_and_persist_memories,
    refresh_rolling_summary,
)

logger = logging.getLogger("worker.memory")

LOCK_TTL = 60 * 5                     # 5 min — prevents double execution per session
CURSOR_TTL = 60 * 60 * 24 * 30        # 30 days
SUMMARY_TTL = 60 * 60 * 24 * 30
ROLLING_SUMMARY_EVERY = 10            # refresh summary every N user turns


def _cursor_key(session_id: str) -> str:
    return f"memory-last-extracted:{session_id}"


def _lock_key(session_id: str) -> str:
    return f"memory-task-lock:{session_id}"


def _summary_key(session_id: str) -> str:
    return f"memory-summary:{session_id}"


def _message_hash(msg: dict) -> str:
    """SHA-256 of role + content. Stable against index reshuffling."""
    content = f"{msg.get('role', '')}:{msg.get('content', '')}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _slice_new_messages(
    messages: list[dict], cursor_hash: Optional[str]
) -> list[dict]:
    """Return only messages the worker hasn't processed yet.

    Falls back to the full list when the cursor can't be located in the current
    messages (summarization collapsed it, or first run).
    """
    if not cursor_hash:
        return messages
    for idx, msg in enumerate(messages):
        if _message_hash(msg) == cursor_hash:
            return messages[idx + 1:]
    logger.info(
        "memory cursor not found in current messages — likely summarization. "
        "Falling back to full message list."
    )
    return messages


def _count_user_turns(messages: list[dict]) -> int:
    return sum(1 for m in messages if isinstance(m, dict) and m.get("role") == "user")


async def persist_memories_task(
    ctx,
    user_id: str,
    messages: list[dict],
    session_id: Optional[str] = None,
):
    sid = session_id or user_id  # fallback when no session context is passed

    lock_acquired = redis_client.set(_lock_key(sid), "1", ex=LOCK_TTL, nx=True)
    if not lock_acquired:
        logger.info("memory task skipped: already running for session %s", sid)
        return {"status": "in_progress"}

    try:
        cursor_hash = redis_client.get(_cursor_key(sid))
        new_messages = _slice_new_messages(messages, cursor_hash)
        if not new_messages:
            logger.info("memory task: no new messages since last extraction")
            return {"status": "skipped_no_new_messages"}

        rolling_summary = redis_client.get(_summary_key(sid))

        try:
            counts = await asyncio.to_thread(
                extract_and_persist_memories,
                new_messages,
                user_id,
                session_id,
                rolling_summary,
            )
        except MemoryExtractionError as exc:
            # Hard parse failure — do NOT advance the cursor, otherwise the
            # failed messages are permanently skipped on the next call.
            logger.warning("memory extraction failed for session %s: %s", sid, exc)
            return {"status": "extraction_failed", "error": str(exc)}

        # Advance cursor to the hash of the last processed message.
        last_hash = _message_hash(messages[-1])
        redis_client.set(_cursor_key(sid), last_hash, ex=CURSOR_TTL)

        # Periodically refresh the rolling summary so long sessions stay cheap
        # and short replies remain interpretable to the extractor.
        user_turn_count = _count_user_turns(messages)
        if user_turn_count > 0 and user_turn_count % ROLLING_SUMMARY_EVERY == 0:
            try:
                updated_summary = await asyncio.to_thread(
                    refresh_rolling_summary, messages, rolling_summary
                )
                if updated_summary:
                    redis_client.set(_summary_key(sid), updated_summary, ex=SUMMARY_TTL)
            except Exception as exc:
                logger.warning(f"rolling summary refresh failed: {exc}")

        return {"status": "ok", "counts": counts}
    finally:
        redis_client.delete(_lock_key(sid))


async def refresh_rolling_summary_task(
    ctx,
    messages: list[dict],
    session_id: str,
):
    """Refresh the stored rolling summary for a session in the background."""
    if not session_id or not messages:
        return {"status": "skipped"}

    previous_summary = redis_client.get(_summary_key(session_id))
    updated_summary = await asyncio.to_thread(
        refresh_rolling_summary,
        messages,
        previous_summary,
    )
    if not updated_summary:
        return {"status": "empty"}

    redis_client.set(_summary_key(session_id), updated_summary, ex=SUMMARY_TTL)
    return {"status": "ok", "summary": updated_summary}


def invalidate_session_memory_cursor(session_id: str) -> None:
    """Clear the cursor so the next extraction processes the summarized
    conversation from scratch. Call this right after ``summarize_messages``
    collapses the message list.
    """
    redis_client.delete(_cursor_key(session_id))
