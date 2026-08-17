"""Business logic rule repository."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_logic import BusinessLogicRule


class BusinessLogicRepository:
    async def get_by_id(self, session: AsyncSession, id: uuid.UUID) -> BusinessLogicRule | None:
        return await session.get(BusinessLogicRule, id)

    async def list_by_schema(
        self, session: AsyncSession, schema_id: uuid.UUID
    ) -> list[BusinessLogicRule]:
        result = await session.execute(
            select(BusinessLogicRule)
            .where(BusinessLogicRule.schema_id == schema_id)
            .order_by(BusinessLogicRule.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_task(
        self, session: AsyncSession, task_id: uuid.UUID
    ) -> list[BusinessLogicRule]:
        result = await session.execute(
            select(BusinessLogicRule)
            .where(BusinessLogicRule.extraction_task_id == task_id)
            .order_by(BusinessLogicRule.created_at)
        )
        return list(result.scalars().all())

    async def create(self, session: AsyncSession, obj: BusinessLogicRule) -> BusinessLogicRule:
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return obj

    async def bulk_create(
        self, session: AsyncSession, objs: list[BusinessLogicRule]
    ) -> list[BusinessLogicRule]:
        session.add_all(objs)
        await session.flush()
        return objs
