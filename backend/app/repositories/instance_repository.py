"""Ontology instance repository."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.instance import InstanceDataValue, OntologyInstance
from app.models.schema import OntologyClass


class InstanceRepository:
    async def get_by_id(self, session: AsyncSession, id: uuid.UUID) -> OntologyInstance | None:
        result = await session.execute(
            select(OntologyInstance)
            .where(OntologyInstance.id == id)
            .options(
                selectinload(OntologyInstance.data_values),
                selectinload(OntologyInstance.subject_relations),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_task(
        self,
        session: AsyncSession,
        task_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[OntologyInstance], int]:
        filt = OntologyInstance.extraction_task_id == task_id
        total = (
            await session.execute(
                select(func.count()).select_from(OntologyInstance).where(filt)
            )
        ).scalar_one()
        result = await session.execute(
            select(OntologyInstance)
            .where(filt)
            .options(selectinload(OntologyInstance.data_values))
            .order_by(OntologyInstance.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    async def list_by_schema(
        self,
        session: AsyncSession,
        schema_id: uuid.UUID,
        *,
        schema_version: int | None = None,
        limit: int | None = None,
        with_details: bool = False,
    ) -> list[OntologyInstance]:
        stmt = select(OntologyInstance).where(OntologyInstance.schema_id == schema_id)
        if schema_version is not None:
            stmt = stmt.where(OntologyInstance.schema_version == schema_version)
        if with_details:
            stmt = stmt.options(
                selectinload(OntologyInstance.data_values),
                selectinload(OntologyInstance.subject_relations),
            )
        stmt = stmt.order_by(OntologyInstance.created_at)
        if limit:
            stmt = stmt.limit(limit)
        return list((await session.execute(stmt)).scalars().all())

    async def list_page(
        self,
        session: AsyncSession,
        schema_id: uuid.UUID,
        *,
        schema_version: int | None = None,
        class_id: uuid.UUID | None = None,
        source_type: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[OntologyInstance], int]:
        filt = [OntologyInstance.schema_id == schema_id]
        if schema_version is not None:
            filt.append(OntologyInstance.schema_version == schema_version)
        if class_id is not None:
            filt.append(OntologyInstance.class_id == class_id)
        if source_type:
            filt.append(OntologyInstance.source_type == source_type)
        total = (
            await session.execute(
                select(func.count()).select_from(OntologyInstance).where(*filt)
            )
        ).scalar_one()
        result = await session.execute(
            select(OntologyInstance)
            .where(*filt)
            .options(selectinload(OntologyInstance.data_values))
            .order_by(OntologyInstance.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    async def list_versions(self, session: AsyncSession, schema_id: uuid.UUID) -> list[int]:
        result = await session.execute(
            select(OntologyInstance.schema_version)
            .where(
                OntologyInstance.schema_id == schema_id,
                OntologyInstance.schema_version.is_not(None),
            )
            .distinct()
            .order_by(OntologyInstance.schema_version.desc())
        )
        return [int(v) for (v,) in result.all() if v is not None]

    async def delete_by_schema(
        self,
        session: AsyncSession,
        schema_id: uuid.UUID,
        *,
        schema_version: int | None = None,
        source_types: list[str] | None = None,
    ) -> int:
        filt = [OntologyInstance.schema_id == schema_id]
        if schema_version is not None:
            filt.append(OntologyInstance.schema_version == schema_version)
        if source_types:
            filt.append(OntologyInstance.source_type.in_(source_types))
        result = await session.execute(delete(OntologyInstance).where(*filt))
        return int(result.rowcount or 0)

    async def find_by_label(
        self,
        session: AsyncSession,
        schema_id: uuid.UUID,
        class_id: uuid.UUID,
        label: str,
    ) -> OntologyInstance | None:
        result = await session.execute(
            select(OntologyInstance).where(
                OntologyInstance.schema_id == schema_id,
                OntologyInstance.class_id == class_id,
                OntologyInstance.label == label,
            )
        )
        return result.scalar_one_or_none()

    async def search(
        self,
        session: AsyncSession,
        schema_id: uuid.UUID,
        *,
        schema_version: int | None = None,
        q: str | None = None,
        class_id: uuid.UUID | None = None,
        limit: int = 20,
    ) -> list[OntologyInstance]:
        filt = [OntologyInstance.schema_id == schema_id]
        if schema_version is not None:
            filt.append(OntologyInstance.schema_version == schema_version)
        if class_id is not None:
            filt.append(OntologyInstance.class_id == class_id)
        stmt = select(OntologyInstance).where(*filt)
        needle = (q or "").strip()
        if needle:
            like = f"%{needle}%"
            stmt = (
                stmt.outerjoin(
                    InstanceDataValue,
                    InstanceDataValue.instance_id == OntologyInstance.id,
                )
                .outerjoin(OntologyClass, OntologyClass.id == OntologyInstance.class_id)
                .where(
                    or_(
                        OntologyInstance.label.ilike(like),
                        OntologyInstance.local_name.ilike(like),
                        InstanceDataValue.value.ilike(like),
                        OntologyClass.label.ilike(like),
                    )
                )
                .distinct()
            )
        stmt = (
            stmt.options(selectinload(OntologyInstance.data_values))
            .order_by(OntologyInstance.created_at.desc())
            .limit(limit)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def find_by_local_name(
        self,
        session: AsyncSession,
        schema_id: uuid.UUID,
        class_id: uuid.UUID,
        local_name: str,
    ) -> OntologyInstance | None:
        result = await session.execute(
            select(OntologyInstance).where(
                OntologyInstance.schema_id == schema_id,
                OntologyInstance.class_id == class_id,
                OntologyInstance.local_name == local_name,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, session: AsyncSession, obj: OntologyInstance) -> OntologyInstance:
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return obj

    async def bulk_create(
        self, session: AsyncSession, objs: list[OntologyInstance]
    ) -> list[OntologyInstance]:
        session.add_all(objs)
        await session.flush()
        return objs

    async def add_data_values(
        self, session: AsyncSession, values: list[InstanceDataValue]
    ) -> None:
        session.add_all(values)
        await session.flush()

    async def replace_data_values(
        self,
        session: AsyncSession,
        instance_id: uuid.UUID,
        values: list[InstanceDataValue],
        *,
        property_ids: list[uuid.UUID] | None = None,
    ) -> None:
        """Replace data values for an instance (optionally scoped to property_ids)."""
        stmt = delete(InstanceDataValue).where(InstanceDataValue.instance_id == instance_id)
        if property_ids is not None:
            stmt = stmt.where(InstanceDataValue.property_id.in_(property_ids))
        await session.execute(stmt)
        if values:
            session.add_all(values)
        await session.flush()

    async def count_by_schema(
        self,
        session: AsyncSession,
        schema_id: uuid.UUID,
        *,
        schema_version: int | None = None,
    ) -> int:
        filt = [OntologyInstance.schema_id == schema_id]
        if schema_version is not None:
            filt.append(OntologyInstance.schema_version == schema_version)
        return (
            await session.execute(
                select(func.count()).select_from(OntologyInstance).where(*filt)
            )
        ).scalar_one()

    async def count_all(self, session: AsyncSession) -> int:
        return (
            await session.execute(select(func.count()).select_from(OntologyInstance))
        ).scalar_one()

    async def count_by_class(
        self,
        session: AsyncSession,
        schema_id: uuid.UUID,
        *,
        schema_version: int | None = None,
    ) -> list[tuple[uuid.UUID, str, int]]:
        join_cond = (OntologyInstance.class_id == OntologyClass.id) & (
            OntologyInstance.schema_id == schema_id
        )
        if schema_version is not None:
            join_cond = join_cond & (OntologyInstance.schema_version == schema_version)
        result = await session.execute(
            select(OntologyClass.id, OntologyClass.label, func.count(OntologyInstance.id))
            .outerjoin(OntologyInstance, join_cond)
            .where(OntologyClass.schema_id == schema_id)
            .group_by(OntologyClass.id, OntologyClass.label)
        )
        return [(r[0], r[1], r[2]) for r in result.all()]

    async def delete(self, session: AsyncSession, obj: OntologyInstance) -> None:
        await session.delete(obj)
        await session.flush()

    async def count_null_class(
        self,
        session: AsyncSession,
        schema_id: uuid.UUID,
        *,
        schema_version: int | None = None,
    ) -> int:
        filt = [
            OntologyInstance.schema_id == schema_id,
            OntologyInstance.class_id.is_(None),
        ]
        if schema_version is not None:
            filt.append(OntologyInstance.schema_version == schema_version)
        return (
            await session.execute(
                select(func.count()).select_from(OntologyInstance).where(*filt)
            )
        ).scalar_one()

    async def count_for_class(self, session: AsyncSession, class_id: uuid.UUID) -> int:
        return (
            await session.execute(
                select(func.count())
                .select_from(OntologyInstance)
                .where(OntologyInstance.class_id == class_id)
            )
        ).scalar_one()
