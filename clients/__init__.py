import os
from dotenv import load_dotenv
from minio import Minio
from llm import build_llm_client

load_dotenv()

_IS_PRODUCTION = os.getenv("APP_ENV") == "production"

llm_client = build_llm_client()
openai_client = llm_client

if _IS_PRODUCTION:
    _minio_access = os.environ["MINIO_ACCESS_KEY"]
    _minio_secret = os.environ["MINIO_SECRET_KEY"]
else:
    _minio_access = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    _minio_secret = os.getenv("MINIO_SECRET_KEY", "minioadmin")

minio_client = Minio(
    os.getenv("MINIO_ENDPOINT", "localhost:9000"),
    access_key=_minio_access,
    secret_key=_minio_secret,
    secure=os.getenv("MINIO_SECURE", "false").lower() == "true",
)


_pinecone_client = None


def __getattr__(name: str):
    global _pinecone_client
    if name == "pinecone_client":
        if _pinecone_client is None:
            from pinecone import Pinecone

            _pinecone_client = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
        return _pinecone_client
    raise AttributeError(f"module 'clients' has no attribute {name!r}")
