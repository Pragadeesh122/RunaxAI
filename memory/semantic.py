"""Atomic memory extraction pipeline.

Two LLM passes, both running in an ARQ worker thread:

1. **Extract** — pull candidate atomic facts from a conversation slice, given
   an optional rolling summary for ambient context.
2. **Consolidate (batched)** — for each candidate, fetch top-k semantically
   similar existing facts via pgvector, then ask a single LLM call to decide
   ADD / UPDATE / DELETE / NONE for every candidate at once.

Storage is Postgres (``user_memory_fact``) using pgvector for similarity search.
Superseded facts are retained with ``superseded_at`` + ``superseded_by`` set —
never hard-deleted — which preserves an audit trail and enables temporal queries.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text as sa_text

from clients import llm_client
from database.core import sync_session_maker
from database.models import UserMemoryFact
from llm.response_utils import extract_first_embedding, extract_first_text
from observability.spans import memory_extraction_span
from prompts.memory import (
    MEMORY_CONSOLIDATION_BATCH,
    MEMORY_EXTRACTION,
    MEMORY_ROLLING_SUMMARY,
)

logger = logging.getLogger("memory")

# ``text-embedding-3-small`` matches the tool cache (memory/cache.py) — keeping
# both on the same model lets them share infrastructure later if needed and
# keeps cost per embedding low.
MEMORY_EMBEDDING_MODEL = "openai/text-embedding-3-small"
MEMORY_EMBEDDING_DIM = 1536
TOP_K_SIMILAR = 5
EMBED_PARALLELISM = 4


def _utc_now_naive() -> datetime:
    """Naive UTC timestamp for existing timestamp-without-time-zone columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _loads_json_lenient(raw: str) -> Optional[dict]:
    """json.loads with one fallback: strip a ```json ... ``` fence if present.

    Defense-in-depth for the rare case where the provider ignores
    response_format. Returns None on unrecoverable parse failure.
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    stripped = raw.strip()
    if stripped.startswith("```"):
        # Drop the opening fence (optionally with a language tag) and the
        # closing fence, then retry.
        first_newline = stripped.find("\n")
        if first_newline != -1:
            body = stripped[first_newline + 1 :]
            if body.rstrip().endswith("```"):
                body = body.rstrip()[:-3]
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return None
    return None


# ─── Embeddings ───────────────────────────────────────────────────────────

def _embed(text: str) -> list[float]:
    response = llm_client.embeddings.create(
        input=text, model=MEMORY_EMBEDDING_MODEL
    )
    return extract_first_embedding(response)


def _embed_many(texts: list[str]) -> list[list[float]]:
    """Embed a batch in parallel. Preserves input order."""
    if not texts:
        return []
    with memory_extraction_span(phase="embed", count=len(texts)):
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(EMBED_PARALLELISM, len(texts))
        ) as pool:
            return list(pool.map(_embed, texts))


# ─── Pass 1 — Extract candidate facts ─────────────────────────────────────

def _format_conversation(messages: list[dict]) -> str:
    """Render messages as a readable transcript for the extractor."""
    lines = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if role not in ("user", "assistant") or not content:
            continue
        lines.append(f"{role}: {content}")
    return "\n\n".join(lines)


def _extract_candidate_facts(
    messages: list[dict],
    rolling_summary: Optional[str],
    observation_date: datetime,
) -> list[str]:
    """Pass 1: one LLM call returning a flat list of atomic fact strings."""
    transcript = _format_conversation(messages)
    if not transcript.strip():
        return []

    summary_block = (
        f"Rolling summary of this session so far:\n{rolling_summary}\n\n"
        if rolling_summary
        else ""
    )
    user_content = (
        f"Observation Date: {observation_date.date().isoformat()}\n\n"
        f"{summary_block}"
        f"Conversation:\n{transcript}"
    )

    with memory_extraction_span(phase="extract", message_count=len(messages)):
        response = llm_client.chat.completions.create(
            messages=[
                {"role": "system", "content": MEMORY_EXTRACTION},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
        )

    raw = extract_first_text(response, "{}")
    parsed = _loads_json_lenient(raw)
    if parsed is None:
        logger.error(f"extraction returned non-JSON: {raw[:200]}")
        return []
    facts = parsed.get("facts", [])
    # Defensive: drop anything that isn't a non-empty string.
    return [f.strip() for f in facts if isinstance(f, str) and f.strip()]


# ─── Pass 2 — Consolidate (batched) ───────────────────────────────────────

def _find_similar_facts(
    session,
    user_id: uuid.UUID,
    embedding: list[float],
    limit: int = TOP_K_SIMILAR,
) -> list:
    """Top-k unsuperseded facts for this user, ordered by cosine distance."""
    vector_literal = "[" + ",".join(repr(float(x)) for x in embedding) + "]"
    rows = session.execute(
        sa_text(
            """
            SELECT id, text, observed_at,
                   (embedding <=> CAST(:vec AS vector)) AS distance
            FROM user_memory_fact
            WHERE user_id = :uid AND superseded_at IS NULL
            ORDER BY distance
            LIMIT :k
            """
        ),
        {"vec": vector_literal, "uid": str(user_id), "k": limit},
    ).fetchall()
    return rows


def _consolidate_batch(
    candidates: list[str],
    similar_map: dict[int, list],
) -> list[dict]:
    """Pass 2: a single LLM call returns a decision per candidate."""
    if not candidates:
        return []

    candidate_blocks = []
    for idx, candidate in enumerate(candidates):
        similar_rows = similar_map.get(idx, [])
        similar_lines = (
            "\n".join(f'  - id={row.id}: "{row.text}"' for row in similar_rows)
            if similar_rows
            else "  (no similar existing facts)"
        )
        candidate_blocks.append(
            f"candidate_index={idx}\n"
            f'candidate: "{candidate}"\n'
            f"similar existing facts:\n{similar_lines}"
        )
    user_content = "\n\n".join(candidate_blocks)

    with memory_extraction_span(phase="consolidate", count=len(candidates)):
        response = llm_client.chat.completions.create(
            messages=[
                {"role": "system", "content": MEMORY_CONSOLIDATION_BATCH},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
        )

    raw = extract_first_text(response, "{}")
    parsed = _loads_json_lenient(raw)
    if parsed is None:
        logger.error(f"consolidation returned non-JSON: {raw[:200]}")
        # Fail-open: treat every candidate as NONE rather than risking bad writes.
        return [{"candidate_index": i, "action": "NONE"} for i in range(len(candidates))]
    decisions = parsed.get("decisions", [])
    # Index decisions by candidate_index so missing entries default to NONE.
    by_index: dict[int, dict] = {}
    for d in decisions:
        if not isinstance(d, dict):
            continue
        idx = d.get("candidate_index")
        if isinstance(idx, int):
            by_index[idx] = d
    return [
        by_index.get(i, {"candidate_index": i, "action": "NONE"})
        for i in range(len(candidates))
    ]


# ─── Persistence ──────────────────────────────────────────────────────────

def _apply_decisions(
    db,
    user_id: uuid.UUID,
    session_id: Optional[str],
    candidates: list[str],
    embeddings: list[list[float]],
    decisions: list[dict],
) -> dict[str, int]:
    """Apply ADD / UPDATE / DELETE / NONE decisions inside a single transaction."""
    counts = {"ADD": 0, "UPDATE": 0, "DELETE": 0, "NONE": 0, "ERROR": 0}
    now = _utc_now_naive()

    for i, candidate in enumerate(candidates):
        decision = decisions[i] if i < len(decisions) else {"action": "NONE"}
        action = decision.get("action", "NONE")

        try:
            if action == "ADD":
                fact = UserMemoryFact(
                    user_id=user_id,
                    text=candidate,
                    embedding=embeddings[i],
                    observed_at=now,
                    source_session_id=session_id,
                )
                db.add(fact)
                counts["ADD"] += 1

            elif action == "UPDATE":
                old_id = decision.get("supersedes_id")
                if not old_id:
                    logger.warning(f"UPDATE missing supersedes_id for candidate {i}")
                    counts["ERROR"] += 1
                    continue
                new_fact = UserMemoryFact(
                    user_id=user_id,
                    text=candidate,
                    embedding=embeddings[i],
                    observed_at=now,
                    source_session_id=session_id,
                )
                db.add(new_fact)
                db.flush()  # populate new_fact.id for the supersedes link
                db.execute(
                    sa_text(
                        "UPDATE user_memory_fact "
                        "SET superseded_at = :now, superseded_by = :new_id "
                        "WHERE id = :old_id AND user_id = :uid "
                        "AND superseded_at IS NULL"
                    ),
                    {
                        "now": now,
                        "new_id": new_fact.id,
                        "old_id": old_id,
                        "uid": str(user_id),
                    },
                )
                counts["UPDATE"] += 1

            elif action == "DELETE":
                target_id = decision.get("target_id")
                if not target_id:
                    logger.warning(f"DELETE missing target_id for candidate {i}")
                    counts["ERROR"] += 1
                    continue
                db.execute(
                    sa_text(
                        "UPDATE user_memory_fact "
                        "SET superseded_at = :now "
                        "WHERE id = :id AND user_id = :uid "
                        "AND superseded_at IS NULL"
                    ),
                    {"now": now, "id": target_id, "uid": str(user_id)},
                )
                counts["DELETE"] += 1

            else:  # NONE or unrecognized
                counts["NONE"] += 1
        except Exception as exc:
            logger.error(f"failed to apply {action} for candidate {i}: {exc}")
            counts["ERROR"] += 1

    return counts


# ─── Main pipeline entry point ────────────────────────────────────────────

def extract_and_persist_memories(
    messages: list[dict],
    user_id: str,
    session_id: Optional[str] = None,
    rolling_summary: Optional[str] = None,
    observation_date: Optional[datetime] = None,
) -> dict:
    """Run both passes and persist the result.

    Returns a counts dict so the ARQ task can log a one-line summary.
    """
    if not messages:
        return {"ADD": 0, "UPDATE": 0, "DELETE": 0, "NONE": 0, "ERROR": 0}

    uid = uuid.UUID(user_id)
    obs_date = observation_date or _utc_now_naive()

    # Pass 1 — extract candidates
    candidates = _extract_candidate_facts(messages, rolling_summary, obs_date)
    if not candidates:
        logger.info("no candidate facts extracted")
        return {"ADD": 0, "UPDATE": 0, "DELETE": 0, "NONE": 0, "ERROR": 0}

    logger.info(f"extracted {len(candidates)} candidate facts")

    # Embed every candidate in parallel
    embeddings = _embed_many(candidates)

    # Fetch similar existing facts for each candidate
    with sync_session_maker() as db, memory_extraction_span(phase="persist"):
        similar_map: dict[int, list] = {}
        for i, emb in enumerate(embeddings):
            similar_map[i] = _find_similar_facts(db, uid, emb)

        decisions = _consolidate_batch(candidates, similar_map)
        counts = _apply_decisions(
            db, uid, session_id, candidates, embeddings, decisions
        )
        db.commit()

    logger.info(
        "memory consolidation: add=%d update=%d delete=%d none=%d error=%d",
        counts["ADD"], counts["UPDATE"], counts["DELETE"],
        counts["NONE"], counts["ERROR"],
    )
    return counts


# ─── Rolling summary ──────────────────────────────────────────────────────

def refresh_rolling_summary(
    messages: list[dict],
    previous_summary: Optional[str] = None,
) -> str:
    """Regenerate a compact session summary for use as extraction context."""
    transcript = _format_conversation(messages)
    if not transcript.strip():
        return previous_summary or ""

    previous_block = (
        f"Previous summary:\n{previous_summary}\n\n" if previous_summary else ""
    )
    user_content = f"{previous_block}Conversation:\n{transcript}"

    with memory_extraction_span(phase="summary", message_count=len(messages)):
        response = llm_client.chat.completions.create(
            messages=[
                {"role": "system", "content": MEMORY_ROLLING_SUMMARY},
                {"role": "user", "content": user_content},
            ],
        )
    return extract_first_text(response, "").strip()


# ─── Retrieval ────────────────────────────────────────────────────────────

def get_user_memory(user_id: str = "") -> str:
    """All unsuperseded facts for this user as a formatted bulleted block.

    Returned string is injected directly into the system prompt. Empty string
    when the user has no memory.
    """
    if not user_id:
        return ""
    try:
        uid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        return ""

    try:
        with sync_session_maker() as db:
            rows = db.execute(
                sa_text(
                    """
                    SELECT text FROM user_memory_fact
                    WHERE user_id = :uid AND superseded_at IS NULL
                    ORDER BY observed_at ASC
                    """
                ),
                {"uid": str(uid)},
            ).fetchall()
        if not rows:
            return ""
        return "\n".join(f"- {row[0]}" for row in rows)
    except Exception as exc:
        logger.error(f"get_user_memory failed: {exc}")
        return ""


# ─── Deprecated shims ─────────────────────────────────────────────────────
# Kept so any straggling import paths don't crash mid-rollout.

def extract_and_save_memories(messages: list, user_id: str = ""):
    if not user_id:
        logger.info("extract_and_save_memories skipped: missing user_id")
        return None
    return extract_and_persist_memories(messages, user_id)


def sync_redis_memory_to_db(user_id: str) -> None:
    # Redis hash is no longer the source of truth; sync is a no-op.
    return None
