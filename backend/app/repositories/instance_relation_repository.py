"""Instance relation repository."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.instance import InstanceRelation, OntologyInstance


class InstanceRelationRepository:
    async def list_by_schema(
        self, session: AsyncSession, schema_id: uuid.UUID, *, limit: int | None = None
    ) -> list[InstanceRelation]:
        stmt = (
            select(InstanceRelation)
            .join(
                OntologyInstance,
                OntologyInstance.id == InstanceRelation.subject_instance_id,
            )
            .where(OntologyInstance.schema_id == schema_id)
        )
        if limit:
            stmt = stmt.limit(limit)
        return list((await session.execute(stmt)).scalars().all())

    async def list_by_subject(
        self, session: AsyncSession, instance_id: uuid.UUID
    ) -> list[InstanceRelation]:
        result = await session.execute(
            select(InstanceRelation).where(
                InstanceRelation.subject_instance_id == instance_id
            )
        )
        return list(result.scalars().all())

    async def list_by_object(
        self, session: AsyncSession, instance_id: uuid.UUID
    ) -> list[InstanceRelation]:
        result = await session.execute(
            select(InstanceRelation).where(
                InstanceRelation.object_instance_id == instance_id
            )
        )
        return list(result.scalars().all())

    async def list_incident(
        self,
        session: AsyncSession,
        instance_ids: list[uuid.UUID],
        *,
        schema_id: uuid.UUID | None = None,
        schema_version: int | None = None,
        property_ids: list[uuid.UUID] | None = None,
    ) -> list[InstanceRelation]:
        if not instance_ids:
            return []
        stmt = select(InstanceRelation).where(
            (InstanceRelation.subject_instance_id.in_(instance_ids))
            | (InstanceRelation.object_instance_id.in_(instance_ids))
        )
        if property_ids:
            stmt = stmt.where(InstanceRelation.property_id.in_(property_ids))
        if schema_id is not None:
            stmt = stmt.join(
                OntologyInstance,
                OntologyInstance.id == InstanceRelation.subject_instance_id,
            ).where(OntologyInstance.schema_id == schema_id)
            if schema_version is not None:
                stmt = stmt.where(OntologyInstance.schema_version == schema_version)
        return list((await session.execute(stmt)).scalars().all())

    async def create(self, session: AsyncSession, obj: InstanceRelation) -> InstanceRelation:
        session.add(obj)
        await session.flush()
        return obj

    async def bulk_create(
        self, session: AsyncSession, objs: list[InstanceRelation]
    ) -> list[InstanceRelation]:
        session.add_all(objs)
        await session.flush()
        return objs
