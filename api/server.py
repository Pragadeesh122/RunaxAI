"""FastAPI server exposing the orchestrator as an API."""

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from pipeline.storage import ensure_bucket, get_presigned_put_url, get_presigned_get_url

from api.session import (
    create_session,
    delete_session,
    get_messages,
    restore_session,
    session_exists,
    session_owned_by_user,
)
from api.chat import chat_stream
from pipeline.chat_attachments import (
    MAX_SESSION_ATTACHMENT_TOKENS,
    MAX_TOKENS_PER_DOCUMENT,
    compute_attachment_tokens,
    find_oversized_attachments,
)
from api.projects import router as projects_router
from api.health import router as health_router
from memory.semantic import _embed
from database.models import ChatSession, User, UserMemoryFact
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database.core import get_db, engine as _db_engine
from api.auth.manager import current_active_user, get_user_manager
from api.chat_sessions import (
    router as chat_sessions_router,
    messages_router as chat_messages_router,
)
from api.rate_limit import rate_limit_middleware

from api.auth.manager import fastapi_users_app
from api.auth.config import auth_backend, google_oauth_client, SECRET
from api.auth.schemas import UserRead, UserCreate, UserUpdate
from api.auth.manager import UserManager

from observability.logging_config import setup_logging
from observability.tracing import setup_tracing

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup — nothing special needed (connections are lazy)
    yield
    # Shutdown — clean up connections
    await _db_engine.dispose()
    from memory.redis_client import redis_client

    redis_client.close()


_DOCS_ENABLED = os.getenv("ENABLE_API_DOCS", "false").lower() == "true"
app = FastAPI(
    title="RunaxAI",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _DOCS_ENABLED else None,
    redoc_url="/redoc" if _DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _DOCS_ENABLED else None,
)

setup_tracing(app)

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total number of HTTP requests.",
    ["method", "path", "status_code"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)


def _metrics_path(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    return request.url.path


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _serialize_memory_fact(fact: UserMemoryFact) -> dict:
    return {
        "id": fact.id,
        "text": fact.text,
        "observed_at": fact.observed_at.isoformat(),
        "source_session_id": fact.source_session_id,
    }


@app.middleware("http")
async def _prometheus_http_middleware(request: Request, call_next):
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        path = _metrics_path(request)
        HTTP_REQUESTS_TOTAL.labels(
            method=request.method,
            path=path,
            status_code=str(status_code),
        ).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(
            method=request.method,
            path=path,
        ).observe(time.perf_counter() - start)


app.middleware("http")(rate_limit_middleware)

CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
# In dev, also match any localhost port. Disable in prod by not setting this var.
_cors_localhost_regex = (
    r"https?://(localhost|127\.0\.0\.1)(:\d+)?$"
    if os.getenv("CORS_ALLOW_LOCALHOST_REGEX", "true").lower() == "true"
    else None
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_origin_regex=_cors_localhost_regex,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Auth Routers
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

app.include_router(
    fastapi_users_app.get_auth_router(auth_backend),
    prefix="/auth",
    tags=["auth"],
)

app.include_router(
    fastapi_users_app.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
)

app.include_router(
    fastapi_users_app.get_reset_password_router(),
    prefix="/auth",
    tags=["auth"],
)

app.include_router(
    fastapi_users_app.get_verify_router(UserRead),
    prefix="/auth",
    tags=["auth"],
)

app.include_router(
    fastapi_users_app.get_oauth_router(
        google_oauth_client,
        auth_backend,
        SECRET,
        associate_by_email=True,
        redirect_url=f"{FRONTEND_URL}/api/auth/callback/google",
    ),
    prefix="/auth/google",
    tags=["auth"],
)

app.include_router(
    fastapi_users_app.get_users_router(UserRead, UserUpdate),
    prefix="/users",
    tags=["users"],
)

app.include_router(health_router)
app.include_router(projects_router)
app.include_router(chat_sessions_router)
app.include_router(chat_messages_router)


@app.get("/metrics", include_in_schema=False)
def metrics(request: Request):
    # Prometheus scrapes via the in-cluster Service (no proxy hop, no XFF
    # header). Public requests come through Traefik which always sets
    # X-Forwarded-For. Reject anything that came through the public ingress.
    if request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip"):
        raise HTTPException(status_code=404)
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


class ChatAttachmentRef(BaseModel):
    id: str
    filename: str
    mimeType: str = ""
    fileSize: int = 0
    storageKey: str


class ChatRequest(BaseModel):
    sessionId: str
    message: str
    attachments: list[ChatAttachmentRef] = Field(default_factory=list)


CHAT_ATTACHMENT_ALLOWED_EXTS = {
    "png", "jpg", "jpeg", "webp", "gif",
    "pdf", "txt", "md", "csv", "docx",
}
CHAT_ATTACHMENT_MAX_BYTES = 20 * 1024 * 1024
CHAT_ATTACHMENT_MAX_PER_MESSAGE = 5
CHAT_SESSION_MAX_FILES = 10
CHAT_SESSION_MAX_BYTES = 20 * 1024 * 1024
CHAT_UPLOAD_PREFIX = "chat"


def _chat_attachment_ext(filename: str) -> str:
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


def _chat_storage_prefix(user_id: str) -> str:
    return f"{CHAT_UPLOAD_PREFIX}/{user_id}/"


class ChatUploadInitRequest(BaseModel):
    filename: str
    fileSize: int = 0
    mimeType: str = ""


class RestoreRequest(BaseModel):
    session_id: str
    messages: list[dict]
    project_name: str | None = None


class MemoryFactCreate(BaseModel):
    text: str


class ChangePasswordData(BaseModel):
    current_password: str
    new_password: str


@app.post("/chat/backend-session")
def new_session(user: User = Depends(current_active_user)):
    """Create a new conversational orchestrator session."""
    session_id = create_session(str(user.id))
    return {"session_id": session_id}


@app.post("/chat/stream")
def chat(req: ChatRequest, user: User = Depends(current_active_user)):
    """Send a message and receive an SSE stream of tokens."""
    if not session_owned_by_user(req.sessionId, str(user.id)):
        raise HTTPException(status_code=404, detail="Session not found")

    if len(req.attachments) > CHAT_ATTACHMENT_MAX_PER_MESSAGE:
        raise HTTPException(
            status_code=400,
            detail=f"At most {CHAT_ATTACHMENT_MAX_PER_MESSAGE} attachments per message",
        )

    user_prefix = _chat_storage_prefix(str(user.id))
    attachments = []
    for att in req.attachments:
        if not att.storageKey.startswith(user_prefix):
            raise HTTPException(status_code=403, detail="Attachment not owned by user")
        if att.fileSize and att.fileSize > CHAT_ATTACHMENT_MAX_BYTES:
            raise HTTPException(status_code=400, detail="Attachment exceeds size limit")
        attachments.append(att.model_dump())

    if attachments:
        chat_logger = logging.getLogger("api.chat_stream")
        chat_logger.info(
            "[token-check] /chat/stream request: %d new attachment(s)",
            len(attachments),
        )
        try:
            existing = get_messages(req.sessionId)
        except KeyError:
            existing = []
        seen_ids: set[str] = set()
        all_refs: list[dict] = []
        for msg in existing:
            for ref in msg.get("attachments") or []:
                rid = ref.get("id")
                if not rid or rid in seen_ids:
                    continue
                seen_ids.add(rid)
                all_refs.append(ref)
        for att in attachments:
            if att["id"] in seen_ids:
                continue
            seen_ids.add(att["id"])
            all_refs.append(att)

        if len(all_refs) > CHAT_SESSION_MAX_FILES:
            raise HTTPException(
                status_code=400,
                detail=f"Session limit reached: at most {CHAT_SESSION_MAX_FILES} files per chat",
            )
        total_bytes = sum(int(r.get("fileSize") or 0) for r in all_refs)
        if total_bytes > CHAT_SESSION_MAX_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"Session limit reached: {CHAT_SESSION_MAX_BYTES // (1024 * 1024)} MB total across all files",
            )

        oversized = find_oversized_attachments(attachments)
        if oversized:
            names = ", ".join(
                f"{att.get('filename') or '?'} ({tokens}t)" for att, tokens in oversized
            )
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Document too dense for chat context: {names}. "
                    f"Max {MAX_TOKENS_PER_DOCUMENT} tokens per file."
                ),
            )

        session_tokens = compute_attachment_tokens(all_refs)
        if session_tokens > MAX_SESSION_ATTACHMENT_TOKENS:
            chat_logger.warning(
                "[token-check] reject session: %d tokens > cap %d",
                session_tokens, MAX_SESSION_ATTACHMENT_TOKENS,
            )
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Total attachment tokens ({session_tokens}) exceed session "
                    f"cap of {MAX_SESSION_ATTACHMENT_TOKENS}. Remove a file to continue."
                ),
            )
        chat_logger.info(
            "[token-check] accept request: %d total tokens, %d file(s) (caps: doc=%d, session=%d)",
            session_tokens, len(all_refs),
            MAX_TOKENS_PER_DOCUMENT, MAX_SESSION_ATTACHMENT_TOKENS,
        )

    try:
        return StreamingResponse(
            chat_stream(req.sessionId, req.message, attachments),
            media_type="text/event-stream",
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


@app.post("/chat/upload")
def chat_upload_init(
    req: ChatUploadInitRequest,
    user: User = Depends(current_active_user),
):
    """Generate a presigned PUT URL for a chat attachment.

    No DB row is created — the user binding lives in the storage key prefix
    (chat/{user_id}/{attachment_id}.{ext}). The frontend is expected to send
    the returned ref back in the next /chat/stream call.
    """
    ext = _chat_attachment_ext(req.filename)
    if ext not in CHAT_ATTACHMENT_ALLOWED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(sorted(CHAT_ATTACHMENT_ALLOWED_EXTS))}",
        )
    if req.fileSize and req.fileSize > CHAT_ATTACHMENT_MAX_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds {CHAT_ATTACHMENT_MAX_BYTES // (1024 * 1024)} MB limit",
        )

    attachment_id = uuid.uuid4().hex
    storage_key = f"{_chat_storage_prefix(str(user.id))}{attachment_id}.{ext}"

    try:
        ensure_bucket()
        upload_url = get_presigned_put_url(storage_key)
    except Exception as exc:
        logging.getLogger("api.chat_upload").error("presign PUT failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to generate upload URL")

    return {
        "id": attachment_id,
        "filename": req.filename,
        "mimeType": req.mimeType,
        "fileSize": req.fileSize,
        "storageKey": storage_key,
        "uploadUrl": upload_url,
    }


@app.get("/chat/attachments/url")
def chat_attachment_url(
    key: str,
    user: User = Depends(current_active_user),
):
    """Return a short-lived presigned GET URL so the frontend can preview/download
    a chat attachment. Validates the key is under the caller's prefix."""
    if not key.startswith(_chat_storage_prefix(str(user.id))):
        raise HTTPException(status_code=403, detail="Attachment not owned by user")
    try:
        url = get_presigned_get_url(key, expires=300)
    except Exception as exc:
        logging.getLogger("api.chat_upload").error("presign GET failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to generate download URL")
    return {"url": url}


@app.get("/session/{session_id}/exists")
def check_session(session_id: str, user: User = Depends(current_active_user)):
    """Check if a session exists in Redis."""
    return {"exists": session_owned_by_user(session_id, str(user.id))}


@app.post("/session/restore")
async def restore(
    req: RestoreRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Restore a Redis session from persisted messages."""
    if session_exists(req.session_id):
        if not session_owned_by_user(req.session_id, str(user.id)):
            raise HTTPException(status_code=404, detail="Session not found")
    else:
        stmt = select(ChatSession).where(
            ChatSession.user_id == user.id,
            ChatSession.backend_session_id == req.session_id,
        )
        owned_session = (await db.execute(stmt)).scalar_one_or_none()
        if not owned_session:
            raise HTTPException(status_code=404, detail="Session not found")

    restore_session(
        req.session_id,
        req.messages,
        str(user.id),
        req.project_name or "",
    )
    return {"status": "restored", "session_id": req.session_id}


@app.delete("/chat/backend-session/{session_id}")
def remove_session(session_id: str, user: User = Depends(current_active_user)):
    """Delete the session from Redis."""
    if not session_owned_by_user(session_id, str(user.id)):
        raise HTTPException(status_code=404, detail="Session not found")
    delete_session(session_id)
    return {"status": "deleted"}


@app.get("/chat/memory")
async def get_chat_memory(
    user=Depends(current_active_user), db: AsyncSession = Depends(get_db)
):
    stmt = (
        select(UserMemoryFact)
        .where(
            UserMemoryFact.user_id == user.id,
            UserMemoryFact.superseded_at.is_(None),
        )
        .order_by(UserMemoryFact.observed_at.desc(), UserMemoryFact.id.desc())
    )
    facts = (await db.execute(stmt)).scalars().all()
    return {"facts": [_serialize_memory_fact(fact) for fact in facts]}


@app.post("/chat/memory")
async def create_chat_memory_fact(
    data: MemoryFactCreate,
    user=Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    text = data.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Memory text cannot be empty")

    existing_stmt = select(UserMemoryFact).where(
        UserMemoryFact.user_id == user.id,
        UserMemoryFact.text == text,
        UserMemoryFact.superseded_at.is_(None),
    )
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing:
        return _serialize_memory_fact(existing)

    embedding = await asyncio.to_thread(_embed, text)
    fact = UserMemoryFact(
        user_id=user.id,
        text=text,
        embedding=embedding,
        observed_at=_utc_now_naive(),
        source_session_id="manual-memory",
    )
    db.add(fact)
    await db.commit()
    await db.refresh(fact)
    return _serialize_memory_fact(fact)


@app.delete("/chat/memory/{fact_id}")
async def delete_chat_memory_fact(
    fact_id: str,
    user=Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(UserMemoryFact).where(
        UserMemoryFact.id == fact_id,
        UserMemoryFact.user_id == user.id,
        UserMemoryFact.superseded_at.is_(None),
    )
    fact = (await db.execute(stmt)).scalar_one_or_none()
    if not fact:
        raise HTTPException(status_code=404, detail="Memory fact not found")

    fact.superseded_at = _utc_now_naive()
    await db.commit()
    return {"status": "ok"}


@app.post("/auth/change-password")
async def change_password(
    data: ChangePasswordData,
    user: User = Depends(current_active_user),
    manager: UserManager = Depends(get_user_manager),
):
    if not user.hashed_password:
        raise HTTPException(
            status_code=400,
            detail="Password changes are unavailable for OAuth-only accounts",
        )

    verified, _ = manager.password_helper.verify_and_update(
        data.current_password,
        user.hashed_password,
    )
    if not verified:
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    await manager.validate_password(data.new_password, user)
    next_hash = manager.password_helper.hash(data.new_password)
    await manager.user_db.update(user, {"hashed_password": next_hash})
    return {"status": "ok"}
