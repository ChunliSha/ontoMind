"""LLM model config repository."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm import LlmModelConfig


class LlmModelRepository:
    async def get_by_id(self, session: AsyncSession, id: uuid.UUID) -> LlmModelConfig | None:
        return await session.get(LlmModelConfig, id)

    async def get_by_name(self, session: AsyncSession, name: str) -> LlmModelConfig | None:
        result = await session.execute(
            select(LlmModelConfig).where(LlmModelConfig.name == name)
        )
        return result.scalar_one_or_none()

    async def get_default(self, session: AsyncSession) -> LlmModelConfig | None:
        result = await session.execute(
            select(LlmModelConfig)
            .where(LlmModelConfig.is_default.is_(True), LlmModelConfig.status == "active")
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        session: AsyncSession,
        *,
        source: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[LlmModelConfig], int]:
        stmt = select(LlmModelConfig)
        count_stmt = select(func.count()).select_from(LlmModelConfig)
        if source:
            stmt = stmt.where(LlmModelConfig.source == source)
            count_stmt = count_stmt.where(LlmModelConfig.source == source)
        if status:
            stmt = stmt.where(LlmModelConfig.status == status)
            count_stmt = count_stmt.where(LlmModelConfig.status == status)
        total = (await session.execute(count_stmt)).scalar_one()
        stmt = (
            stmt.order_by(LlmModelConfig.is_default.desc(), LlmModelConfig.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list((await session.execute(stmt)).scalars().all()), total

    async def list_active(self, session: AsyncSession) -> list[LlmModelConfig]:
        result = await session.execute(
            select(LlmModelConfig)
            .where(LlmModelConfig.status == "active")
            .order_by(LlmModelConfig.is_default.desc(), LlmModelConfig.name)
        )
        return list(result.scalars().all())

    async def create(self, session: AsyncSession, obj: LlmModelConfig) -> LlmModelConfig:
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return obj

    async def update(self, session: AsyncSession, obj: LlmModelConfig) -> LlmModelConfig:
        await session.flush()
        await session.refresh(obj)
        return obj

    async def delete(self, session: AsyncSession, obj: LlmModelConfig) -> None:
        await session.delete(obj)
        await session.flush()

    async def clear_default(self, session: AsyncSession) -> None:
        await session.execute(
            update(LlmModelConfig).where(LlmModelConfig.is_default.is_(True)).values(is_default=False)
        )
        await session.flush()
