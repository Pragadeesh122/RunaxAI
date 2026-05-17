"""Nuke all RAG state so you can reingest at a different embedding dimension.

Wipes three stores:
  1. Pinecone — deletes the `agenticrag` index entirely. ensure_index() will
     recreate it at the currently-configured DENSE_EMBEDDING_DIMENSION on
     next backend boot.
  2. MinIO — deletes every object in the `agenticrag-documents` bucket.
  3. Postgres — deletes every Document row across every project.

Projects, users, chat sessions, and messages are preserved — only the
document side of the world is reset. Users will see their empty projects
on next login and can reupload.

Usage::

    uv run python -m scripts.reset_rag           # confirms before deleting
    uv run python -m scripts.reset_rag --yes     # skip confirmation
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import delete, func, select

from clients import minio_client, pinecone_client
from database.core import sync_session_maker
from database.models import Document
from pipeline.pinecone_helpers import INDEX_NAME
from pipeline.storage import BUCKET_NAME

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("scripts.reset_rag")


def _count_documents() -> int:
    with sync_session_maker() as session:
        return session.scalar(select(func.count()).select_from(Document)) or 0


def _count_minio_objects() -> int:
    if not minio_client.bucket_exists(BUCKET_NAME):
        return 0
    return sum(1 for _ in minio_client.list_objects(BUCKET_NAME, recursive=True))


def _index_exists() -> bool:
    return INDEX_NAME in {idx.name for idx in pinecone_client.list_indexes()}


def _confirm(doc_count: int, object_count: int, index_present: bool) -> bool:
    print()
    print("About to delete:")
    print(f"  - {doc_count} Document rows from Postgres")
    print(f"  - {object_count} objects from MinIO bucket '{BUCKET_NAME}'")
    print(
        f"  - Pinecone index '{INDEX_NAME}'"
        if index_present
        else f"  - (Pinecone index '{INDEX_NAME}' not present — skipping)"
    )
    print()
    print("Projects, users, chat sessions, and messages are NOT touched.")
    print()
    answer = input("Type 'yes' to proceed: ").strip().lower()
    return answer == "yes"


def _wipe_documents() -> int:
    with sync_session_maker() as session:
        result = session.execute(delete(Document))
        session.commit()
        deleted = result.rowcount or 0
    logger.info(f"deleted {deleted} Document rows")
    return deleted


def _wipe_minio() -> int:
    if not minio_client.bucket_exists(BUCKET_NAME):
        logger.info(f"bucket '{BUCKET_NAME}' does not exist — skipping")
        return 0
    count = 0
    for obj in minio_client.list_objects(BUCKET_NAME, recursive=True):
        minio_client.remove_object(BUCKET_NAME, obj.object_name)
        count += 1
    logger.info(f"deleted {count} objects from bucket '{BUCKET_NAME}'")
    return count


def _wipe_pinecone() -> bool:
    if not _index_exists():
        logger.info(f"Pinecone index '{INDEX_NAME}' not present — skipping")
        return False
    pinecone_client.delete_index(INDEX_NAME)
    logger.info(f"deleted Pinecone index '{INDEX_NAME}'")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="skip the interactive confirmation",
    )
    args = parser.parse_args()

    doc_count = _count_documents()
    object_count = _count_minio_objects()
    index_present = _index_exists()

    if doc_count == 0 and object_count == 0 and not index_present:
        print("Nothing to delete. RAG state is already empty.")
        return 0

    if not args.yes and not _confirm(doc_count, object_count, index_present):
        print("Aborted.")
        return 1

    _wipe_documents()
    _wipe_minio()
    _wipe_pinecone()

    print()
    print("Done. Restart the backend — ensure_index() will recreate the")
    print("Pinecone index at the currently-configured DENSE_EMBEDDING_DIMENSION.")
    print("Then reupload your documents through the UI.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
