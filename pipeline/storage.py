"""MinIO object storage helpers for document upload and retrieval."""

import logging
from datetime import timedelta
from functools import lru_cache
from urllib.parse import urlsplit
import os

from minio import Minio
from clients import minio_client

logger = logging.getLogger("pipeline.storage")

_IS_PRODUCTION = os.getenv("APP_ENV") == "production"

BUCKET_NAME = "agenticrag-documents"


def ensure_bucket() -> None:
    """Create the bucket if it doesn't exist."""
    if not minio_client.bucket_exists(BUCKET_NAME):
        minio_client.make_bucket(BUCKET_NAME)
        logger.info(f"created bucket '{BUCKET_NAME}'")


@lru_cache(maxsize=1)
def _presign_client() -> Minio:
    """Client used only for generating browser-facing presigned URLs.

    Signature validation depends on the host used for signing. If we sign with
    an internal host (e.g. minio:9000) and later rewrite to localhost:9000,
    direct browser PUT/GET can fail with signature mismatch.
    """
    public_base = os.getenv("MINIO_PUBLIC_BASE_URL", "").strip()
    if not public_base:
        return minio_client

    normalized = public_base if "://" in public_base else f"http://{public_base}"
    parsed = urlsplit(normalized)
    endpoint = parsed.netloc or parsed.path
    if not endpoint:
        logger.warning(
            "invalid MINIO_PUBLIC_BASE_URL='%s'; falling back to internal MinIO endpoint",
            public_base,
        )
        return minio_client

    if _IS_PRODUCTION:
        access_key = os.environ["MINIO_ACCESS_KEY"]
        secret_key = os.environ["MINIO_SECRET_KEY"]
    else:
        access_key = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
        secret_key = os.getenv("MINIO_SECRET_KEY", "minioadmin")

    return Minio(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=(parsed.scheme.lower() == "https"),
        region=os.getenv("MINIO_REGION", "us-east-1"),
    )


def put_object_stream(
    object_key: str,
    fileobj,
    length: int,
    content_type: str | None = None,
) -> None:
    """Stream an object into MinIO using internal credentials.

    Used by auth-gated upload endpoints so the browser never receives a
    presigned PUT URL (which is a bearer token).
    """
    ensure_bucket()
    minio_client.put_object(
        BUCKET_NAME,
        object_key,
        fileobj,
        length=length,
        content_type=content_type or "application/octet-stream",
    )
    logger.info(f"stored '{object_key}' ({length} bytes)")


def get_presigned_get_url(object_key: str, expires: int = 3600) -> str:
    """Generate a presigned GET URL for browser document viewing/downloading."""
    ensure_bucket()
    url = _presign_client().presigned_get_object(
        BUCKET_NAME,
        object_key,
        expires=timedelta(seconds=expires),
    )
    return url


def get_object_stream(object_key: str):
    """Return the raw MinIO HTTPResponse for an object.

    Caller is responsible for ``close()`` and ``release_conn()`` on the
    response. Used by auth-gated streaming endpoints so the browser never
    receives a presigned GET URL (which is a bearer token).
    """
    return minio_client.get_object(BUCKET_NAME, object_key)


def stat_object(object_key: str):
    """Return MinIO object stat (size, content-type, etag, etc.)."""
    return minio_client.stat_object(BUCKET_NAME, object_key)


def download_to_bytes(object_key: str) -> bytes:
    """Download an object from MinIO and return its bytes."""
    response = minio_client.get_object(BUCKET_NAME, object_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def download_to_file(object_key: str, file_path: str) -> str:
    """Download an object from MinIO to a local file path.

    Returns the file_path for convenience.
    """
    minio_client.fget_object(BUCKET_NAME, object_key, file_path)
    logger.info(f"downloaded '{object_key}' → '{file_path}'")
    return file_path


def delete_object(object_key: str) -> None:
    """Delete a single object from MinIO."""
    minio_client.remove_object(BUCKET_NAME, object_key)
    logger.info(f"deleted object '{object_key}'")


def delete_project_objects(project_id: str) -> None:
    """Delete all objects under a project prefix."""
    objects = minio_client.list_objects(BUCKET_NAME, prefix=f"{project_id}/")
    for obj in objects:
        minio_client.remove_object(BUCKET_NAME, obj.object_name)
    logger.info(f"deleted all objects for project '{project_id}'")
