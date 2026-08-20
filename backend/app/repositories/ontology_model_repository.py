"""Ontology model repository."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ontology_model import OntologyModel


class OntologyModelRepository:
    async def get_by_id(self, session: AsyncSession, id: uuid.UUID) -> OntologyModel | None:
        return await session.get(OntologyModel, id)

    async def get_by_name(self, session: AsyncSession, name: str) -> OntologyModel | None:
        result = await session.execute(
            select(OntologyModel).where(OntologyModel.name == name)
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        session: AsyncSession,
        *,
        schema_id: uuid.UUID | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[OntologyModel], int]:
        stmt = select(OntologyModel)
        count_stmt = select(func.count()).select_from(OntologyModel)
        if schema_id:
            stmt = stmt.where(OntologyModel.schema_id == schema_id)
            count_stmt = count_stmt.where(OntologyModel.schema_id == schema_id)
        if search:
            filt = OntologyModel.name.ilike(f"%{search}%")
            stmt = stmt.where(filt)
            count_stmt = count_stmt.where(filt)
        total = (await session.execute(count_stmt)).scalar_one()
        stmt = (
            stmt.order_by(OntologyModel.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list((await session.execute(stmt)).scalars().all()), total

    async def create(self, session: AsyncSession, obj: OntologyModel) -> OntologyModel:
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return obj

    async def delete(self, session: AsyncSession, obj: OntologyModel) -> None:
        await session.delete(obj)
        await session.flush()
