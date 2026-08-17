"""Field mapping repository."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.mapping import FieldMapping, FieldMappingBinding


class MappingRepository:
    async def get_by_id(self, session: AsyncSession, id: uuid.UUID) -> FieldMapping | None:
        result = await session.execute(
            select(FieldMapping)
            .where(FieldMapping.id == id)
            .options(selectinload(FieldMapping.bindings))
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        session: AsyncSession,
        *,
        schema_id: uuid.UUID | None = None,
        class_id: uuid.UUID | None = None,
    ) -> list[FieldMapping]:
        stmt = select(FieldMapping).options(selectinload(FieldMapping.bindings))
        if schema_id:
            stmt = stmt.where(FieldMapping.schema_id == schema_id)
        if class_id:
            stmt = stmt.where(FieldMapping.class_id == class_id)
        result = await session.execute(stmt.order_by(FieldMapping.created_at.desc()))
        return list(result.scalars().all())

    async def get_by_class_table(
        self, session: AsyncSession, class_id: uuid.UUID, table_id: uuid.UUID
    ) -> FieldMapping | None:
        result = await session.execute(
            select(FieldMapping)
            .where(FieldMapping.class_id == class_id, FieldMapping.table_id == table_id)
            .options(selectinload(FieldMapping.bindings))
        )
        return result.scalar_one_or_none()

    async def create(self, session: AsyncSession, obj: FieldMapping) -> FieldMapping:
        session.add(obj)
        await session.flush()
        await session.refresh(obj, attribute_names=["bindings"])
        return obj

    async def replace_bindings(
        self,
        session: AsyncSession,
        mapping: FieldMapping,
        bindings: list[FieldMappingBinding],
    ) -> FieldMapping:
        await session.execute(
            delete(FieldMappingBinding).where(FieldMappingBinding.mapping_id == mapping.id)
        )
        for b in bindings:
            b.mapping_id = mapping.id
            session.add(b)
        await session.flush()
        await session.refresh(mapping, attribute_names=["bindings"])
        return mapping

    async def delete(self, session: AsyncSession, obj: FieldMapping) -> None:
        await session.delete(obj)
        await session.flush()
