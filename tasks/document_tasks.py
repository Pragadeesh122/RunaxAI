import asyncio
import logging
from pipeline.ingestion import ingest_document
from pipeline.retrieval_cache import invalidate_project_cache
from database.core import async_session_maker
from observability.task_instrumentation import instrumented_task
from services.document_service import DocumentService

logger = logging.getLogger("worker.tasks")

@instrumented_task
async def process_document_task(ctx, object_key: str, project_id: str, document_id: str, filename: str):
    """
    ARQ task to parse, chunk, embed, and upload documents to Vector DB.
    Finally updates the PostgreSQL document record.
    """
    try:
        result = await asyncio.to_thread(
            ingest_document,
            object_key=object_key,
            project_id=project_id,
            document_id=document_id,
            filename=filename,
        )

        async with async_session_maker() as session:
            doc_service = DocumentService(session)
            await doc_service.mark_ready(document_id, count=result["chunk_count"])

        invalidate_project_cache(project_id)
        logger.info(f"document '{document_id}' processed successfully: {result['chunk_count']} chunks")
        
    except Exception as e:
        logger.error(f"document '{document_id}' processing failed: {e}")
        async with async_session_maker() as session:
            doc_service = DocumentService(session)
            await doc_service.mark_failed(document_id, err=str(e))
