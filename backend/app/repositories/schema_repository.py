"""Ontology schema repository."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schema import GraphCache, OntologySchema


class SchemaRepository:
    async def get_by_id(self, session: AsyncSession, id: uuid.UUID) -> OntologySchema | None:
        return await session.get(OntologySchema, id)

    async def list(
        self,
        session: AsyncSession,
        *,
        search: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[OntologySchema], int]:
        stmt = select(OntologySchema)
        count_stmt = select(func.count()).select_from(OntologySchema)
        if search:
            filt = OntologySchema.name.ilike(f"%{search}%")
            stmt = stmt.where(filt)
            count_stmt = count_stmt.where(filt)
        total = (await session.execute(count_stmt)).scalar_one()
        stmt = (
            stmt.order_by(OntologySchema.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list((await session.execute(stmt)).scalars().all()), total

    async def create(self, session: AsyncSession, obj: OntologySchema) -> OntologySchema:
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return obj

    async def update(self, session: AsyncSession, obj: OntologySchema) -> OntologySchema:
        await session.flush()
        await session.refresh(obj)
        return obj

    async def delete(self, session: AsyncSession, obj: OntologySchema) -> None:
        await session.delete(obj)
        await session.flush()

    async def count_all(self, session: AsyncSession) -> int:
        return (
            await session.execute(select(func.count()).select_from(OntologySchema))
        ).scalar_one()

    async def count_published(self, session: AsyncSession) -> int:
        return (
            await session.execute(
                select(func.count())
                .select_from(OntologySchema)
                .where(OntologySchema.status == "published")
            )
        ).scalar_one()

    async def invalidate_graph_cache(self, session: AsyncSession, schema_id: uuid.UUID) -> None:
        await session.execute(delete(GraphCache).where(GraphCache.schema_id == schema_id))
        await session.flush()

    async def get_graph_cache(
        self, session: AsyncSession, schema_id: uuid.UUID, mode: str
    ) -> GraphCache | None:
        return await session.get(GraphCache, {"schema_id": schema_id, "mode": mode})

    async def upsert_graph_cache(
        self, session: AsyncSession, schema_id: uuid.UUID, mode: str, payload: dict
    ) -> GraphCache:
        existing = await self.get_graph_cache(session, schema_id, mode)
        if existing:
            existing.payload = payload
            await session.flush()
            return existing
        cache = GraphCache(schema_id=schema_id, mode=mode, payload=payload)
        session.add(cache)
        await session.flush()
        return cache
