"""Hybrid rate-limiting middleware: user-based (JWT) with IP fallback, sliding window."""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections import deque

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse

from api.auth.config import SECRET
from memory.redis_client import redis_client

logger = logging.getLogger("api.rate_limit")

# ---------------------------------------------------------------------------
# Rate limit rules
# ---------------------------------------------------------------------------

RATE_LIMIT_RULES = (
    {
        "name": "auth_login",
        "method": "POST",
        "pattern": re.compile(r"^/auth/login$"),
        "limit": 5,
        "window": 60,
    },
    {
        "name": "auth_register",
        "method": "POST",
        "pattern": re.compile(r"^/auth/register$"),
        "limit": 5,
        "window": 60,
    },
    {
        "name": "chat_stream",
        "method": "POST",
        "pattern": re.compile(r"^/chat/stream$"),
        "limit": 20,
        "window": 60,
    },
    {
        "name": "project_chat",
        "method": "POST",
        "pattern": re.compile(r"^/projects/[^/]+/chat$"),
        "limit": 20,
        "window": 60,
    },
    {
        "name": "project_document_upload",
        "method": "POST",
        "pattern": re.compile(r"^/projects/[^/]+/documents$"),
        "limit": 20,
        "window": 60,
    },
    {
        "name": "project_document_reingest",
        "method": "PUT",
        "pattern": re.compile(r"^/projects/[^/]+/documents/[^/]+/file$"),
        "limit": 20,
        "window": 60,
    },
)

# ---------------------------------------------------------------------------
# Subject extraction
# ---------------------------------------------------------------------------

COOKIE_NAME = "app_token"
JWT_ALGORITHM = "HS256"
JWT_AUDIENCE = "fastapi-users:auth"


def _extract_user_id_from_token(request: Request) -> str | None:
    """Decode the JWT to get user_id without the full FastAPI-Users auth stack.

    Returns None (fall back to IP) on any failure — expired, malformed, missing.
    """
    token = request.cookies.get(COOKIE_NAME)

    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ")

    if not token:
        return None

    try:
        payload = jwt.decode(
            token,
            SECRET,
            algorithms=[JWT_ALGORITHM],
            audience=JWT_AUDIENCE,
        )
        sub = payload.get("sub")
        return f"user:{sub}" if sub else None
    except jwt.PyJWTError:
        return None


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def get_rate_limit_subject(request: Request) -> str:
    """Try user_id from JWT, fall back to IP."""
    user_subject = _extract_user_id_from_token(request)
    if user_subject:
        return user_subject
    return f"ip:{_client_ip(request)}"


# ---------------------------------------------------------------------------
# Rule matching
# ---------------------------------------------------------------------------

def match_rate_limit_rule(request: Request) -> dict | None:
    path = request.url.path
    method = request.method.upper()
    for rule in RATE_LIMIT_RULES:
        if rule["method"] == method and rule["pattern"].match(path):
            return rule
    return None


# ---------------------------------------------------------------------------
# Sliding window — Redis sorted set via Lua script
# ---------------------------------------------------------------------------

_SLIDING_WINDOW_LUA = """\
local key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
local cutoff = now_ms - window_ms

redis.call("ZREMRANGEBYSCORE", key, "-inf", cutoff)
local count = redis.call("ZCARD", key)
if count >= limit then
    local oldest = redis.call("ZRANGE", key, 0, 0, "WITHSCORES")
    local retry_after_ms = window_ms - (now_ms - tonumber(oldest[2]))
    return {0, count, retry_after_ms}
end
redis.call("ZADD", key, now_ms, member)
redis.call("PEXPIRE", key, window_ms)
return {1, count + 1, 0}
"""

_lua_script = None


def _get_lua_script():
    global _lua_script
    if _lua_script is None:
        _lua_script = redis_client.register_script(_SLIDING_WINDOW_LUA)
    return _lua_script


# ---------------------------------------------------------------------------
# In-memory fallback (deque-based sliding window)
# ---------------------------------------------------------------------------

_RATE_LIMIT_FALLBACK: dict[str, deque[float]] = {}


def _consume_sliding_window_fallback(
    key: str, limit: int, window: float,
) -> tuple[bool, int, int]:
    """In-process sliding-window fallback when Redis is unavailable."""
    now = time.time()
    dq = _RATE_LIMIT_FALLBACK.setdefault(key, deque())
    cutoff = now - window

    while dq and dq[0] <= cutoff:
        dq.popleft()

    if len(dq) >= limit:
        retry_after = window - (now - dq[0])
        return False, 0, max(int(retry_after), 1)

    dq.append(now)
    remaining = limit - len(dq)
    return True, remaining, 0


# ---------------------------------------------------------------------------
# Core consume function
# ---------------------------------------------------------------------------

def consume_rate_limit(
    rule: dict, subject: str,
) -> tuple[bool, int, int]:
    """Consume one request against the sliding-window rate limiter.

    Returns (allowed, remaining, retry_after_seconds).
    """
    key = f"ratelimit:sw:{rule['name']}:{subject}"
    now_ms = int(time.time() * 1000)
    window_ms = rule["window"] * 1000
    limit = rule["limit"]
    member = f"{now_ms}:{uuid.uuid4().hex[:8]}"

    try:
        script = _get_lua_script()
        result = script(
            keys=[key],
            args=[now_ms, window_ms, limit, member],
        )
        allowed = int(result[0]) == 1
        count = int(result[1])
        retry_after_ms = int(result[2])

        if allowed:
            remaining = limit - count
        else:
            remaining = 0

        retry_after = max(retry_after_ms // 1000, 1) if not allowed else 0
        return allowed, remaining, retry_after

    except Exception as e:
        logger.warning(f"Redis rate-limit failed, using in-memory fallback: {e}")
        return _consume_sliding_window_fallback(key, limit, rule["window"])


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

async def rate_limit_middleware(request: Request, call_next):
    """Hybrid rate-limiting middleware: user-based with IP fallback."""
    rule = match_rate_limit_rule(request)
    if rule is None:
        return await call_next(request)

    subject = get_rate_limit_subject(request)
    allowed, remaining, retry_after = consume_rate_limit(rule, subject)

    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(rule["limit"]),
                "X-RateLimit-Remaining": "0",
            },
        )

    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(rule["limit"])
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    return response
