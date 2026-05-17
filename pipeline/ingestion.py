"""Ingestion orchestrator: extract -> chunk -> embed -> upsert to Pinecone."""

import logging
import os
import tempfile

from pipeline.extractor import extract_text
from pipeline.chunker import chunk_pages
from pipeline.embedder import embed_dense, embed_sparse
from pipeline.pinecone_helpers import ensure_index, upsert_vectors
from pipeline.storage import download_to_file
from observability.spans import ingestion_span

logger = logging.getLogger("pipeline.ingestion")

# Pinecone allows 40KB per metadata field, but we cap text at 8000 chars to
# keep payloads small. If a chunk exceeds this, retrieved text will be a
# silent suffix-truncation of what was embedded — worth knowing about.
METADATA_TEXT_LIMIT = 8000


def ingest_document(
    object_key: str,
    project_id: str,
    document_id: str,
    filename: str,
    chunk_size: int = 2000,
    chunk_overlap: int = 300,
) -> dict:
    """Full ingestion pipeline for a single document.

    Downloads the file from MinIO, then runs extract -> chunk -> embed -> upsert.

    Args:
        object_key: MinIO object key (e.g. "project_id/document_id.pdf")
        project_id: Project ID for Pinecone namespace
        document_id: Document ID for vector metadata
        filename: Original filename (used for extension detection)
        chunk_size: Target chunk size in characters (~400-500 tokens)
        chunk_overlap: Overlap between chunks in characters

    Returns:
        {"chunk_count": int, "chunk_strategy": str}
    """
    with ingestion_span(
        span_name="ingestion.document",
        **{"document.id": document_id, "project.id": project_id},
    ) as root_span:
        ensure_index()

        # Download from MinIO to a temp file
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        tmp_dir = tempfile.mkdtemp(prefix="agenticrag_")
        file_path = os.path.join(tmp_dir, f"{document_id}.{ext}")

        try:
            logger.info(f"downloading '{object_key}' from MinIO")
            download_to_file(object_key, file_path)

            # 1. Extract text
            with ingestion_span(span_name="ingestion.extract"):
                logger.info(f"extracting text from '{file_path}'")
                pages = extract_text(file_path)
                if not pages:
                    raise ValueError(f"No text extracted from '{filename}'")

            logger.info(f"extracted {len(pages)} pages/sections")

            # 2. Chunk
            with ingestion_span(span_name="ingestion.chunk") as chunk_span:
                chunks, strategy = chunk_pages(pages, chunk_size, chunk_overlap)
                if not chunks:
                    raise ValueError(f"No chunks produced from '{filename}'")
                if chunk_span is not None:
                    chunk_span.set_attribute("chunk_count", len(chunks))
                    chunk_span.set_attribute("chunk_strategy", strategy)

            logger.info(f"produced {len(chunks)} chunks using '{strategy}'")

            # 3. Embed (dense + sparse)
            with ingestion_span(span_name="ingestion.embed"):
                texts = [c["text"] for c in chunks]
                dense_embeddings = embed_dense(texts)
                sparse_embeddings = embed_sparse(texts)

            # 4. Build vectors with metadata (Pinecone rejects null values)
            vectors = []
            running_offset = 0
            truncated_count = 0
            for i, chunk in enumerate(chunks):
                vector_id = f"{document_id}_{i}"
                chunk_text = chunk["text"]
                if len(chunk_text) > METADATA_TEXT_LIMIT:
                    truncated_count += 1
                    chunk_text = chunk_text[:METADATA_TEXT_LIMIT]
                metadata = {
                    "text": chunk_text,
                    "source": chunk["source"],
                    "chunk_index": chunk["chunk_index"],
                    "start_index": running_offset,
                    "document_id": document_id,
                    "project_id": project_id,
                }
                # Only include page if it's a real value (PDFs)
                if chunk.get("page_number") is not None:
                    metadata["page"] = chunk["page_number"]

                vectors.append({
                    "id": vector_id,
                    "values": dense_embeddings[i],
                    "sparse_values": sparse_embeddings[i],
                    "metadata": metadata,
                })
                running_offset += len(chunk["text"])

            if truncated_count:
                logger.warning(
                    f"truncated {truncated_count}/{len(chunks)} chunks "
                    f"to {METADATA_TEXT_LIMIT} chars for Pinecone metadata "
                    "— retrieved text will be a suffix-truncated copy of the embedded text"
                )

            # 5. Upsert to Pinecone
            with ingestion_span(span_name="ingestion.upsert"):
                upsert_vectors(project_id, vectors)

            logger.info(
                f"ingested document '{document_id}': "
                f"{len(chunks)} chunks, strategy='{strategy}'"
            )

            if root_span is not None:
                root_span.set_attribute("chunk_count", len(chunks))
                root_span.set_attribute("chunk_strategy", strategy)

            return {"chunk_count": len(chunks), "chunk_strategy": strategy}

        finally:
            # Clean up temp file
            if os.path.exists(file_path):
                os.remove(file_path)
            if os.path.exists(tmp_dir):
                os.rmdir(tmp_dir)
