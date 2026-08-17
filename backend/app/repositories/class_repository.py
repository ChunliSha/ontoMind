"""Ontology class repository."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schema import OntologyClass, OntologyProperty


class ClassRepository:
    async def get_by_id(self, session: AsyncSession, id: uuid.UUID) -> OntologyClass | None:
        return await session.get(OntologyClass, id)

    async def list_by_schema(
        self, session: AsyncSession, schema_id: uuid.UUID
    ) -> list[OntologyClass]:
        result = await session.execute(
            select(OntologyClass)
            .where(OntologyClass.schema_id == schema_id)
            .order_by(OntologyClass.created_at)
        )
        return list(result.scalars().all())

    async def get_by_label(
        self, session: AsyncSession, schema_id: uuid.UUID, label: str
    ) -> OntologyClass | None:
        result = await session.execute(
            select(OntologyClass).where(
                OntologyClass.schema_id == schema_id, OntologyClass.label == label
            )
        )
        return result.scalar_one_or_none()

    async def create(self, session: AsyncSession, obj: OntologyClass) -> OntologyClass:
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return obj

    async def bulk_create(
        self, session: AsyncSession, objs: list[OntologyClass]
    ) -> list[OntologyClass]:
        session.add_all(objs)
        await session.flush()
        return objs

    async def update(self, session: AsyncSession, obj: OntologyClass) -> OntologyClass:
        await session.flush()
        await session.refresh(obj)
        return obj

    async def delete(self, session: AsyncSession, obj: OntologyClass) -> None:
        await session.delete(obj)
        await session.flush()

    async def count_by_schema(self, session: AsyncSession, schema_id: uuid.UUID) -> int:
        return (
            await session.execute(
                select(func.count())
                .select_from(OntologyClass)
                .where(OntologyClass.schema_id == schema_id)
            )
        ).scalar_one()

    async def count_all(self, session: AsyncSession) -> int:
        return (
            await session.execute(select(func.count()).select_from(OntologyClass))
        ).scalar_one()

    async def property_counts(
        self, session: AsyncSession, schema_id: uuid.UUID
    ) -> dict[uuid.UUID, int]:
        result = await session.execute(
            select(OntologyProperty.domain_class_id, func.count())
            .where(OntologyProperty.schema_id == schema_id)
            .group_by(OntologyProperty.domain_class_id)
        )
        return {row[0]: row[1] for row in result.all()}
