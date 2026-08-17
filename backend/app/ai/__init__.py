"""LLM provider factory — env default or per-model config."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import LLMProvider
from app.ai.mock_provider import MockLLMProvider
from app.ai.openai_compatible_provider import OpenAICompatibleProvider
from app.core.config import settings
from app.core.exceptions import AppError, ErrorCode
from app.core.security import decrypt_password
from app.repositories.llm_model_repository import LlmModelRepository


def get_llm_provider() -> LLMProvider:
    """Fallback from .env when no model_id is provided."""
    if settings.LLM_PROVIDER == "openai_compatible":
        return OpenAICompatibleProvider()
    return MockLLMProvider()


async def resolve_llm_provider(
    session: AsyncSession,
    model_id: str | uuid.UUID | None = None,
) -> LLMProvider:
    """Resolve provider from llm_model_config (preferred) or env default."""
    repo = LlmModelRepository()
    cfg = None
    if model_id:
        mid = model_id if isinstance(model_id, uuid.UUID) else uuid.UUID(str(model_id))
        cfg = await repo.get_by_id(session, mid)
        if not cfg:
            raise AppError(ErrorCode.LLM_001)
        if cfg.status == "disabled":
            raise AppError(ErrorCode.CONFLICT, message="所选模型已禁用，请更换模型")
    else:
        cfg = await repo.get_default(session)

    if cfg is None:
        return get_llm_provider()

    if cfg.provider == "mock":
        return MockLLMProvider()

    api_key = decrypt_password(cfg.api_key_enc) if cfg.api_key_enc else None
    return OpenAICompatibleProvider(
        api_base=cfg.api_base,
        api_key=api_key,
        model=cfg.model_name,
    )
