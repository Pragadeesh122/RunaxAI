"""Adaptive text chunking strategies for the RAG pipeline."""

import re
import logging

logger = logging.getLogger("pipeline.chunker")

# Separators ordered from coarsest to finest
SEPARATORS = ["\n\n\n", "\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""]


def chunk_pages(
    pages: list[dict],
    chunk_size: int = 2000,
    chunk_overlap: int = 300,
    strategy: str | None = None,
) -> tuple[list[dict], str]:
    """Chunk extracted pages into smaller pieces for embedding.

    Args:
        pages: list of {"text", "page_number", "source"} from extractor
        chunk_size: target chunk size in characters (~400-500 tokens)
        chunk_overlap: overlap between consecutive chunks in characters
        strategy: force a specific strategy, or None to auto-select

    Returns:
        (chunks, strategy_used) where chunks is list of
        {"text", "page_number", "source", "chunk_index"}
    """
    if not pages:
        return [], "none"

    # Clean text before chunking
    pages = [
        {**p, "text": _clean_text(p["text"])}
        for p in pages
        if p["text"].strip()
    ]

    if not pages:
        return [], "none"

    # Auto-select strategy based on content
    if strategy is None:
        strategy = _select_strategy(pages)

    logger.info(f"chunking {len(pages)} pages with strategy '{strategy}'")

    if strategy == "recursive":
        chunks = _recursive_chunk(pages, chunk_size, chunk_overlap)
    elif strategy == "semantic":
        chunks = _semantic_chunk(pages, chunk_size, chunk_overlap)
    elif strategy == "row_based":
        # CSV data — pages are already chunked by row groups
        chunks = [
            {"text": p["text"], "page_number": p["page_number"],
             "source": p["source"], "chunk_index": i}
            for i, p in enumerate(pages)
        ]
    else:
        chunks = _recursive_chunk(pages, chunk_size, chunk_overlap)

    # Filter out empty/tiny chunks
    chunks = [c for c in chunks if len(c["text"].strip()) > 20]

    # Re-index after filtering
    for i, c in enumerate(chunks):
        c["chunk_index"] = i

    logger.info(f"produced {len(chunks)} chunks using '{strategy}'")
    return chunks, strategy


def _clean_text(text: str) -> str:
    """Normalize text to remove common artifacts before chunking."""
    # Collapse runs of 3+ newlines into 2
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Collapse runs of spaces/tabs (not newlines) into single space
    text = re.sub(r'[^\S\n]+', ' ', text)
    # Remove lines that are only whitespace
    text = re.sub(r'\n +\n', '\n\n', text)
    # Strip leading/trailing whitespace on each line
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(lines)
    # Remove page number artifacts (common in PDFs): standalone numbers on a line
    text = re.sub(r'\n\d{1,4}\n', '\n', text)
    # Remove repeated header/footer lines (exact duplicates appearing 3+ times)
    text = _remove_repeated_lines(text, min_repeats=3)
    return text.strip()


def _remove_repeated_lines(text: str, min_repeats: int = 3) -> str:
    """Remove lines that appear min_repeats or more times (likely headers/footers)."""
    lines = text.split('\n')
    line_counts: dict[str, int] = {}
    for line in lines:
        stripped = line.strip()
        if stripped and len(stripped) < 200:  # Only check short lines
            line_counts[stripped] = line_counts.get(stripped, 0) + 1

    repeated = {line for line, count in line_counts.items() if count >= min_repeats}
    if not repeated:
        return text

    filtered = [line for line in lines if line.strip() not in repeated]
    return '\n'.join(filtered)


def _select_strategy(pages: list[dict]) -> str:
    """Pick the best chunking strategy based on content characteristics."""
    total_text = "".join(p["text"] for p in pages)

    # CSV-style data (already chunked by extractor)
    if any("Columns:" in p["text"] for p in pages):
        return "row_based"

    # Documents with clear section headers → semantic chunking
    header_count = len(re.findall(r'^#{1,6}\s', total_text, re.MULTILINE))
    if header_count >= 3 and len(total_text) > 2000:
        return "semantic"

    # Default: recursive splitting
    return "recursive"


_PAGE_JOINER = "\n\n"


def _recursive_chunk(
    pages: list[dict],
    chunk_size: int,
    overlap: int,
) -> list[dict]:
    """Concat pages, chunk the full doc, then attribute chunks back to pages.

    Page-by-page chunking truncates sentences that span a page break. We
    instead build a single string with an offset map so chunks can flow
    across boundaries; each chunk inherits the page where its start offset
    lives.
    """
    if not pages:
        return []

    parts: list[str] = []
    # (start_offset, end_offset, page_number, source)
    page_map: list[tuple[int, int, int | None, str]] = []
    offset = 0

    for page in pages:
        text = page["text"]
        if not text:
            continue
        if parts:
            parts.append(_PAGE_JOINER)
            offset += len(_PAGE_JOINER)
        start = offset
        parts.append(text)
        offset += len(text)
        page_map.append((start, offset, page["page_number"], page["source"]))

    full_text = "".join(parts)
    if not full_text:
        return []

    fallback_source = pages[0]["source"]
    segments = _split_recursive(full_text, chunk_size, SEPARATORS)

    chunks: list[dict] = []
    search_pos = 0
    chunk_index = 0

    for segment in segments:
        stripped = segment.strip()
        if not stripped:
            continue

        # _split_recursive returns substrings of full_text, so find the
        # offset by stepping forward from where we last matched.
        idx = full_text.find(segment, search_pos)
        if idx < 0:
            idx = full_text.find(segment)
        if idx >= 0:
            search_pos = idx + len(segment)
        else:
            idx = 0  # shouldn't happen, but stay safe

        page_num: int | None = None
        source = fallback_source
        for start, end, p_num, src in page_map:
            if start <= idx < end:
                page_num = p_num
                source = src
                break

        chunks.append({
            "text": stripped,
            "page_number": page_num,
            "source": source,
            "chunk_index": chunk_index,
        })
        chunk_index += 1

    if overlap > 0 and len(chunks) > 1:
        chunks = _apply_overlap(chunks, chunk_size, overlap)

    return chunks


def _split_recursive(
    text: str,
    max_size: int,
    separators: list[str] | None = None,
) -> list[str]:
    """Recursively split text using progressively finer separators."""
    if separators is None:
        separators = SEPARATORS

    if len(text) <= max_size:
        return [text]

    for i, sep in enumerate(separators):
        if sep == "":
            # Last resort: hard split
            return [text[j:j + max_size] for j in range(0, len(text), max_size)]

        parts = text.split(sep)
        if len(parts) <= 1:
            continue

        # Recombine parts into chunks that fit within max_size
        result = []
        current = ""
        for part in parts:
            # Build candidate by joining with separator
            candidate = current + sep + part if current else part
            if len(candidate) > max_size and current:
                result.append(current)
                current = part
            else:
                current = candidate

        if current:
            result.append(current)

        # Only useful if we actually split
        if len(result) <= 1:
            continue

        # Recurse on any pieces still over max_size using finer separators
        final = []
        remaining_seps = separators[i + 1:]
        for r in result:
            if len(r) > max_size and remaining_seps:
                final.extend(_split_recursive(r, max_size, remaining_seps))
            else:
                final.append(r)
        return final

    # Fallback: hard character split
    return [text[j:j + max_size] for j in range(0, len(text), max_size)]


def _semantic_chunk(
    pages: list[dict],
    chunk_size: int,
    overlap: int,
) -> list[dict]:
    """Split by markdown headers, keeping sections together when possible."""
    chunks = []
    chunk_index = 0

    for page in pages:
        text = page["text"]
        page_num = page["page_number"]
        source = page["source"]

        # Split on markdown headers
        sections = re.split(r'(^#{1,6}\s.*$)', text, flags=re.MULTILINE)

        current_header = ""
        current_body = ""

        for section in sections:
            section = section.strip()
            if not section:
                continue

            if re.match(r'^#{1,6}\s', section):
                # Flush previous section
                if current_body.strip():
                    section_text = f"{current_header}\n{current_body}".strip()
                    for sub_chunk in _split_recursive(section_text, chunk_size):
                        chunks.append({
                            "text": sub_chunk.strip(),
                            "page_number": page_num,
                            "source": source,
                            "chunk_index": chunk_index,
                        })
                        chunk_index += 1

                current_header = section
                current_body = ""
            else:
                current_body += "\n" + section

        # Flush last section
        if current_body.strip():
            section_text = f"{current_header}\n{current_body}".strip()
            for sub_chunk in _split_recursive(section_text, chunk_size):
                chunks.append({
                    "text": sub_chunk.strip(),
                    "page_number": page_num,
                    "source": source,
                    "chunk_index": chunk_index,
                })
                chunk_index += 1

    # Apply overlap
    if overlap > 0 and len(chunks) > 1:
        chunks = _apply_overlap(chunks, chunk_size, overlap)

    return chunks


def _apply_overlap(
    chunks: list[dict],
    chunk_size: int,
    overlap: int,
) -> list[dict]:
    """Add overlap by prepending context from previous chunk, respecting sentence boundaries."""
    if len(chunks) <= 1:
        return chunks

    result = [chunks[0]]
    for i in range(1, len(chunks)):
        prev_text = chunks[i - 1]["text"]

        # Get the tail of the previous chunk for overlap
        if len(prev_text) <= overlap:
            overlap_text = prev_text
        else:
            tail = prev_text[-overlap:]
            # Try to start at a sentence boundary within the tail
            sentence_start = _find_sentence_start(tail)
            overlap_text = tail[sentence_start:]

        if not overlap_text.strip():
            result.append(chunks[i])
            continue

        # Only prepend if it doesn't make the chunk excessively large
        new_text = overlap_text.strip() + "\n" + chunks[i]["text"]
        if len(new_text) <= chunk_size * 1.5:
            chunks[i] = {**chunks[i], "text": new_text}

        result.append(chunks[i])

    return result


def _find_sentence_start(text: str) -> int:
    """Find the start of the first complete sentence in text.

    Returns the index of the first character after a sentence boundary,
    or 0 if no boundary is found.
    """
    # Look for sentence-ending punctuation followed by space and uppercase letter
    match = re.search(r'[.!?]\s+(?=[A-Z])', text)
    if match:
        return match.end()

    # Look for newline boundaries
    match = re.search(r'\n\s*', text)
    if match:
        return match.end()

    return 0
