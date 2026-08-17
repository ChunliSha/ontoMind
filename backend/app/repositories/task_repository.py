"""Extraction task repository."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.extraction import ExtractionTask


class TaskRepository:
    async def get_by_id(self, session: AsyncSession, id: uuid.UUID) -> ExtractionTask | None:
        return await session.get(ExtractionTask, id)

    async def create(self, session: AsyncSession, obj: ExtractionTask) -> ExtractionTask:
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return obj

    async def update(self, session: AsyncSession, obj: ExtractionTask) -> ExtractionTask:
        await session.flush()
        await session.refresh(obj)
        return obj

    async def find_running(
        self,
        session: AsyncSession,
        *,
        task_type: str,
        schema_id: uuid.UUID | None = None,
    ) -> ExtractionTask | None:
        stmt = select(ExtractionTask).where(
            ExtractionTask.task_type == task_type,
            ExtractionTask.status.in_(("pending", "running")),
        )
        if schema_id:
            stmt = stmt.where(ExtractionTask.schema_id == schema_id)
        result = await session.execute(stmt.limit(1))
        return result.scalar_one_or_none()

    async def list_by_schema(
        self,
        session: AsyncSession,
        *,
        schema_id: uuid.UUID | None = None,
        task_type: str | None = None,
        limit: int = 20,
    ) -> list[ExtractionTask]:
        stmt = select(ExtractionTask)
        if schema_id:
            stmt = stmt.where(ExtractionTask.schema_id == schema_id)
        if task_type:
            stmt = stmt.where(ExtractionTask.task_type == task_type)
        stmt = stmt.order_by(ExtractionTask.created_at.desc()).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def list_recent(
        self, session: AsyncSession, *, limit: int = 20
    ) -> list[ExtractionTask]:
        result = await session.execute(
            select(ExtractionTask).order_by(ExtractionTask.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())
