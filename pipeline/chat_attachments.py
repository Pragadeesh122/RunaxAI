"""Resolve general-chat attachments into LLM content blocks.

Images become {"type": "image_url", ...} blocks pointing at a presigned MinIO URL.
Documents (pdf/docx/csv/md/txt) are downloaded, text-extracted, and inlined as
text blocks so the LLM can read their content directly.
"""

import base64
import logging
import os
import tempfile
from functools import lru_cache
from typing import Iterable

import pymupdf

from pipeline.extractor import extract_text, SUPPORTED_TYPES as DOC_TYPES
from pipeline.storage import (
    download_to_file,
    get_presigned_get_url,
)

try:
    from litellm import token_counter as _litellm_token_counter
except Exception:  # pragma: no cover
    _litellm_token_counter = None

logger = logging.getLogger("pipeline.chat_attachments")

IMAGE_MIME_PREFIX = "image/"
IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "gif"}

# Maximum tokens a single document can contribute to the chat context. The
# general-chat MAX_PROMPT_TOKENS is 30k; leaving ~5k headroom keeps even a
# capped file from singlehandedly blowing the budget and triggering a
# summarization loop.
MAX_TOKENS_PER_DOCUMENT = 25_000

# Maximum cumulative tokens from all attachments referenced in a single chat
# session. Matches the per-document cap so the worst case is "one max file"
# rather than N small files quietly adding up to a context-blowing total.
MAX_SESSION_ATTACHMENT_TOKENS = 25_000

# Anthropic and OpenAI tokenize PDFs roughly per-page when sent as native file
# blocks. Anthropic's docs cite ~1.5–3k tokens per page; we use the lower end
# so the cap maps to a generous page count for users without overshooting.
NATIVE_PDF_TOKENS_PER_PAGE = 1_500

# Reference model used only for token counting before the LLM call. The
# tokenizers across modern OpenAI/Anthropic chat models agree closely enough
# that a single reference here is sufficient for sizing decisions.
_TOKEN_COUNT_MODEL = "gpt-4o"

# Presigned GET URL TTL for image links handed to the LLM. The provider fetches
# the URL during the request; the URL is regenerated every time we rebuild context.
IMAGE_URL_TTL = 600


def _count_tokens(text: str) -> int:
    if not text:
        return 0
    if _litellm_token_counter is None:
        return len(text) // 4
    try:
        return int(_litellm_token_counter(model=_TOKEN_COUNT_MODEL, text=text) or 0)
    except Exception:
        return len(text) // 4


def _ext_from(att: dict) -> str:
    filename = att.get("filename") or ""
    if "." in filename:
        return filename.rsplit(".", 1)[-1].lower()
    return ""


def _is_image(att: dict) -> bool:
    mime = (att.get("mimeType") or "").lower()
    if mime.startswith(IMAGE_MIME_PREFIX):
        return True
    return _ext_from(att) in IMAGE_EXTS


def _resolve_image(att: dict) -> dict | None:
    storage_key = att.get("storageKey")
    if not storage_key:
        return None
    try:
        url = get_presigned_get_url(storage_key, expires=IMAGE_URL_TTL)
    except Exception as exc:
        logger.warning("failed to presign image '%s': %s", storage_key, exc)
        return None
    return {"type": "image_url", "image_url": {"url": url}}


@lru_cache(maxsize=128)
def _pdf_native_cached(storage_key: str) -> tuple[bytes, int]:
    """Download a PDF and return ``(bytes, estimated_tokens)``.

    Token count is estimated from page count via ``pymupdf`` — the cheapest
    way to size a PDF without extracting its text. Cached so a 20-turn chat
    referencing the same PDF only downloads it once.
    """
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        download_to_file(storage_key, tmp_path)
        with open(tmp_path, "rb") as fh:
            data = fh.read()
        with pymupdf.open(tmp_path) as doc:
            pages = doc.page_count
    except Exception as exc:
        logger.warning("failed to read PDF '%s': %s", storage_key, exc)
        return (b"", 0)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    tokens = pages * NATIVE_PDF_TOKENS_PER_PAGE
    logger.info(
        "[token-check] pdf sized: %d pages × %d tok/page = ~%d tokens (cap %d)",
        pages, NATIVE_PDF_TOKENS_PER_PAGE, tokens, MAX_TOKENS_PER_DOCUMENT,
    )
    return (data, tokens)


def _attachment_token_estimate(att: dict) -> int:
    """Cached token-count estimate for an attachment. 0 for images/unknown."""
    if _is_image(att):
        return 0
    ext = _ext_from(att)
    storage_key = att.get("storageKey")
    if not storage_key:
        return 0
    if ext == "pdf":
        _, tokens = _pdf_native_cached(storage_key)
        return tokens
    if ext in DOC_TYPES:
        _, tokens = _extract_cached(storage_key, ext)
        return tokens
    return 0


@lru_cache(maxsize=128)
def _extract_cached(storage_key: str, ext: str) -> tuple[str, int]:
    """Download, extract, and tokenize a document. Cached per process.

    Returns ``(text, token_count)``. On extraction failure returns ``("", 0)``.
    Cached so a 20-turn chat with the same PDF does one extraction, not twenty.
    The token count is computed once and cached alongside the text so the
    request-time size check is O(1).
    """
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
            tmp_path = tmp.name
        download_to_file(storage_key, tmp_path)
        sections = extract_text(tmp_path)
    except Exception as exc:
        logger.warning("failed to extract '%s': %s", storage_key, exc)
        return ("", 0)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    if not sections:
        return ("", 0)

    parts = []
    for section in sections:
        text = (section.get("text") or "").strip()
        if not text:
            continue
        page = section.get("page_number")
        if page is not None:
            parts.append(f"[page {page}]\n{text}")
        else:
            parts.append(text)
    body = "\n\n".join(parts)
    if not body:
        return ("", 0)

    tokens = _count_tokens(body)
    logger.info(
        "[token-check] doc extracted: ext=%s chars=%d tokens=%d (cap %d)",
        ext, len(body), tokens, MAX_TOKENS_PER_DOCUMENT,
    )
    return (body, tokens)


def _resolve_pdf_native(att: dict) -> dict | None:
    """Build a native PDF content block (base64 file_data) for the LLM.

    Skips extraction entirely — the model handles layout, tables, and embedded
    images on its own. Size enforcement happens via page-count token estimate.
    """
    storage_key = att.get("storageKey")
    filename = att.get("filename") or "attachment.pdf"
    if not storage_key:
        return None
    data, tokens = _pdf_native_cached(storage_key)
    if not data:
        return None
    if tokens > MAX_TOKENS_PER_DOCUMENT:
        logger.warning(
            "[token-check] reject PDF: ~%d tokens > cap %d",
            tokens, MAX_TOKENS_PER_DOCUMENT,
        )
        return None
    logger.info(
        "[token-check] accept PDF: ~%d tokens (cap %d)",
        tokens, MAX_TOKENS_PER_DOCUMENT,
    )
    b64 = base64.b64encode(data).decode("ascii")
    return {
        "type": "file",
        "file": {
            "filename": filename,
            "file_data": f"data:application/pdf;base64,{b64}",
        },
    }


def _resolve_document(att: dict) -> dict | None:
    ext = _ext_from(att)
    if ext == "pdf":
        return _resolve_pdf_native(att)

    storage_key = att.get("storageKey")
    filename = att.get("filename") or "attachment"
    if ext not in DOC_TYPES:
        logger.warning("skipping unsupported attachment type '%s' for %s", ext, filename)
        return None
    if not storage_key:
        return None

    body, tokens = _extract_cached(storage_key, ext)
    if not body:
        return None
    if tokens > MAX_TOKENS_PER_DOCUMENT:
        logger.warning(
            "[token-check] reject doc: ext=%s tokens=%d > cap %d",
            ext, tokens, MAX_TOKENS_PER_DOCUMENT,
        )
        return None
    logger.info(
        "[token-check] accept doc: ext=%s tokens=%d (cap %d)",
        ext, tokens, MAX_TOKENS_PER_DOCUMENT,
    )
    return {
        "type": "text",
        "text": f"[Attached file: {filename}]\n{body}",
    }


def compute_attachment_tokens(attachments: Iterable[dict]) -> int:
    """Sum cached token estimates across document attachments.

    PDFs are estimated per page; other docs use full text extraction token
    counts; images contribute 0. Callers can use this freely — the underlying
    caches make repeat calls O(1).
    """
    refs = list(attachments)
    total = sum(_attachment_token_estimate(att) for att in refs)
    logger.info(
        "[token-check] session total: %d tokens across %d attachment(s) (cap %d)",
        total, len(refs), MAX_SESSION_ATTACHMENT_TOKENS,
    )
    return total


def find_oversized_attachments(attachments: Iterable[dict]) -> list[tuple[dict, int]]:
    """Return (attachment, token_estimate) for documents over the per-doc cap."""
    refs = list(attachments)
    out: list[tuple[dict, int]] = []
    for att in refs:
        tokens = _attachment_token_estimate(att)
        if tokens > MAX_TOKENS_PER_DOCUMENT:
            out.append((att, tokens))
    if out:
        logger.warning(
            "[token-check] %d of %d new attachment(s) exceed per-doc cap %d",
            len(out), len(refs), MAX_TOKENS_PER_DOCUMENT,
        )
    return out


def resolve_to_content_block(att: dict) -> dict | None:
    """Convert one attachment ref into an OpenAI-style content block.

    Returns None if the attachment can't be resolved (the caller should drop it).
    """
    if _is_image(att):
        return _resolve_image(att)
    return _resolve_document(att)


def build_user_content(text: str, attachments: Iterable[dict] | None) -> str | list[dict]:
    """Build a user-message ``content`` value.

    With no attachments we keep the existing plain-string shape so downstream
    paths (Redis history, summarizer, memory extraction) are unchanged. With
    attachments we return the OpenAI list-form content array — the user's text
    first, then one block per attachment.
    """
    refs = list(attachments or [])
    if not refs:
        return text

    blocks: list[dict] = []
    if text:
        blocks.append({"type": "text", "text": text})

    for att in refs:
        block = resolve_to_content_block(att)
        if block is not None:
            blocks.append(block)

    if not blocks:
        return text
    if len(blocks) == 1 and blocks[0].get("type") == "text":
        return blocks[0]["text"]
    return blocks


def prepare_messages_for_llm(messages: list[dict]) -> list[dict]:
    """Resolve attachment refs in each message into multimodal content blocks.

    Walks the conversation and, for any user message carrying an ``attachments``
    field (refs only), rebuilds its content as a list of blocks via
    ``build_user_content``. Messages without attachments are passed through
    unchanged. The ``attachments`` field is stripped from the returned messages
    since it isn't part of the OpenAI message schema.
    """
    out: list[dict] = []
    for msg in messages:
        refs = msg.get("attachments") if isinstance(msg, dict) else None
        if not refs:
            if isinstance(msg, dict) and "attachments" in msg:
                msg = {k: v for k, v in msg.items() if k != "attachments"}
            out.append(msg)
            continue

        text = msg.get("content") if isinstance(msg.get("content"), str) else ""
        rebuilt = {k: v for k, v in msg.items() if k != "attachments"}
        rebuilt["content"] = build_user_content(text, refs)
        out.append(rebuilt)
    return out
