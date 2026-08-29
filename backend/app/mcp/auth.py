"""MCP API key hashing and request authentication."""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppError, ErrorCode
from app.repositories.mcp_repository import McpApiKeyRepository

_keys = McpApiKeyRepository()


def hash_mcp_key(raw: str) -> str:
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()


def extract_mcp_token(authorization: str | None, x_api_key: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    if x_api_key:
        return x_api_key.strip()
    return ""


async def assert_mcp_key(
    session: AsyncSession | None,
    authorization: str | None,
    x_api_key: str | None,
) -> None:
    token = extract_mcp_token(authorization, x_api_key)
    env_key = (settings.MCP_API_KEY or "").strip()
    if not token:
        if settings.MCP_REQUIRE_API_KEY or env_key:
            raise AppError(ErrorCode.KNOWLEDGE_003, message="需要 MCP API Key")
        return
    if env_key and hmac.compare_digest(token, env_key):
        return
    if session is None:
        raise AppError(ErrorCode.KNOWLEDGE_003)
    row = await _keys.get_by_hash(session, hash_mcp_key(token))
    if not row:
        raise AppError(ErrorCode.KNOWLEDGE_003)
    row.last_used_at = datetime.now(timezone.utc)
