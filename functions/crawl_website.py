import asyncio
import json
import logging
from typing import Any

from clients import llm_client
from llm.response_utils import extract_first_text

logger = logging.getLogger("crawl4ai-tool")

SCHEMA = {
    "type": "function",
    "function": {
        "name": "crawl_website",
        "description": (
            "Extract clean content from one known webpage URL using Crawl4AI. "
            "Use this when you already have the exact page URL and need the page's main content "
            "or a focused answer from that specific page. Prefer this over search for single-page extraction. "
            "Do not fan this tool out in parallel when a follow-up decision may depend on what the page says. "
            "It returns JSON with the final URL, title, extracted markdown, top links, and optional focused extraction."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The exact webpage URL to crawl and extract content from.",
                },
                "question": {
                    "type": "string",
                    "description": (
                        "Optional focused question to answer from the crawled page content. "
                        "If omitted, the tool returns the extracted page content and metadata."
                    ),
                },
            },
            "required": ["url"],
        },
    },
}

CACHEABLE = False
POLICY = {
    "execution_mode": "sequential_first",
    "max_parallel_instances": 1,
    "requires_fresh_input": True,
    "dedupe_key_fields": ("url", "question"),
    "verification_only_after_result": True,
}
MAX_MARKDOWN_CHARS = 12000

QUESTION_ANSWER_PROMPT = """You extract answers from a crawled webpage.

Rules:
- Use only the provided page content.
- If the answer is not on the page, say so clearly.
- Keep the answer concise and factual.
- Return valid JSON with keys: answer, evidence.
"""


def _get_result_title(result: Any) -> str:
    metadata = getattr(result, "metadata", None) or {}
    if isinstance(metadata, dict):
        title = metadata.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()

    for attr in ("title", "page_title"):
        value = getattr(result, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return ""


def _get_result_markdown(result: Any) -> str:
    markdown = getattr(result, "markdown", "")
    if isinstance(markdown, str):
        return markdown

    # Crawl4AI may return a markdown wrapper object depending on version/config.
    for attr in ("fit_markdown", "markdown", "raw_markdown"):
        value = getattr(markdown, attr, None)
        if isinstance(value, str) and value.strip():
            return value

    return str(markdown or "")


def _get_result_links(result: Any) -> list[str]:
    links = getattr(result, "links", None)
    if not isinstance(links, dict):
        return []

    collected: list[str] = []
    for bucket in ("internal", "external"):
        entries = links.get(bucket) or []
        if not isinstance(entries, list):
            continue
        for entry in entries[:5]:
            if isinstance(entry, dict):
                href = entry.get("href") or entry.get("url")
                if isinstance(href, str) and href:
                    collected.append(href)
    return collected[:10]


def _answer_question(url: str, title: str, question: str, markdown: str) -> dict[str, str]:
    response = llm_client.chat.completions.create(
        messages=[
            {"role": "system", "content": QUESTION_ANSWER_PROMPT},
            {
                "role": "user",
                "content": (
                    f"URL: {url}\n"
                    f"Title: {title or 'Unknown'}\n"
                    f"Question: {question}\n\n"
                    f"Page content:\n{markdown[:MAX_MARKDOWN_CHARS]}"
                ),
            },
        ],
        response_format={"type": "json_object"},
    )

    try:
        return json.loads(extract_first_text(response, "{}"))
    except json.JSONDecodeError:
        return {
            "answer": extract_first_text(response, ""),
            "evidence": "",
        }


async def _crawl(url: str, question: str | None = None) -> dict[str, Any]:
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig
    except ImportError as e:
        raise RuntimeError(
            "Crawl4AI is not installed. Run `uv sync` and `uv run crawl4ai-setup` first."
        ) from e

    # --disable-dev-shm-usage: k8s pods get a 64MB /dev/shm by default;
    # Chromium crashes on heavy pages unless it falls back to /tmp.
    browser_config = BrowserConfig(extra_args=["--disable-dev-shm-usage"])
    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url)

    success = getattr(result, "success", True)
    if success is False:
        error_message = getattr(result, "error_message", None) or "crawl failed"
        raise RuntimeError(str(error_message))

    final_url = getattr(result, "url", None) or url
    title = _get_result_title(result)
    markdown = _get_result_markdown(result).strip()
    links = _get_result_links(result)

    payload: dict[str, Any] = {
        "url": final_url,
        "title": title,
        "content_markdown": markdown[:MAX_MARKDOWN_CHARS],
        "truncated": len(markdown) > MAX_MARKDOWN_CHARS,
        "links": links,
    }

    if question:
        payload["question"] = question
        payload["extraction"] = _answer_question(final_url, title, question, markdown)

    return payload


def crawl_website(url: str, question: str | None = None) -> dict[str, Any]:
    logger.info(f"crawl4ai extracting: {url}")
    return asyncio.run(_crawl(url, question))
