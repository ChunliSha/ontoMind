"""Ontology property repository."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schema import OntologyProperty


class PropertyRepository:
    async def get_by_id(self, session: AsyncSession, id: uuid.UUID) -> OntologyProperty | None:
        return await session.get(OntologyProperty, id)

    async def list_by_class(
        self, session: AsyncSession, class_id: uuid.UUID
    ) -> list[OntologyProperty]:
        result = await session.execute(
            select(OntologyProperty)
            .where(OntologyProperty.domain_class_id == class_id)
            .order_by(OntologyProperty.created_at)
        )
        return list(result.scalars().all())

    async def list_by_schema(
        self, session: AsyncSession, schema_id: uuid.UUID
    ) -> list[OntologyProperty]:
        result = await session.execute(
            select(OntologyProperty)
            .where(OntologyProperty.schema_id == schema_id)
            .order_by(OntologyProperty.created_at)
        )
        return list(result.scalars().all())

    async def get_by_label(
        self, session: AsyncSession, domain_class_id: uuid.UUID, label: str
    ) -> OntologyProperty | None:
        result = await session.execute(
            select(OntologyProperty).where(
                OntologyProperty.domain_class_id == domain_class_id,
                OntologyProperty.label == label,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, session: AsyncSession, obj: OntologyProperty) -> OntologyProperty:
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return obj

    async def bulk_create(
        self, session: AsyncSession, objs: list[OntologyProperty]
    ) -> list[OntologyProperty]:
        session.add_all(objs)
        await session.flush()
        return objs

    async def update(self, session: AsyncSession, obj: OntologyProperty) -> OntologyProperty:
        await session.flush()
        await session.refresh(obj)
        return obj

    async def delete(self, session: AsyncSession, obj: OntologyProperty) -> None:
        await session.delete(obj)
        await session.flush()

    async def count_by_schema(self, session: AsyncSession, schema_id: uuid.UUID) -> int:
        return (
            await session.execute(
                select(func.count())
                .select_from(OntologyProperty)
                .where(OntologyProperty.schema_id == schema_id)
            )
        ).scalar_one()
