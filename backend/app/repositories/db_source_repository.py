"""Database source repository."""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_source import DataSourceDb


class DbSourceRepository:
    async def get_by_id(self, session: AsyncSession, id: uuid.UUID) -> DataSourceDb | None:
        return await session.get(DataSourceDb, id)

    async def get_by_name(self, session: AsyncSession, name: str) -> DataSourceDb | None:
        result = await session.execute(select(DataSourceDb).where(DataSourceDb.name == name))
        return result.scalar_one_or_none()

    async def list(
        self,
        session: AsyncSession,
        *,
        search: str | None = None,
        db_type: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[DataSourceDb], int]:
        stmt = select(DataSourceDb)
        count_stmt = select(func.count()).select_from(DataSourceDb)
        if search:
            pattern = f"%{search}%"
            filt = or_(DataSourceDb.name.ilike(pattern), DataSourceDb.host.ilike(pattern))
            stmt = stmt.where(filt)
            count_stmt = count_stmt.where(filt)
        if db_type:
            stmt = stmt.where(DataSourceDb.db_type == db_type)
            count_stmt = count_stmt.where(DataSourceDb.db_type == db_type)
        if status:
            stmt = stmt.where(DataSourceDb.status == status)
            count_stmt = count_stmt.where(DataSourceDb.status == status)
        total = (await session.execute(count_stmt)).scalar_one()
        stmt = (
            stmt.order_by(DataSourceDb.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await session.execute(stmt)).scalars().all()
        return list(rows), total

    async def create(self, session: AsyncSession, obj: DataSourceDb) -> DataSourceDb:
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return obj

    async def update(self, session: AsyncSession, obj: DataSourceDb) -> DataSourceDb:
        await session.flush()
        await session.refresh(obj)
        return obj

    async def delete(self, session: AsyncSession, obj: DataSourceDb) -> None:
        await session.delete(obj)
        await session.flush()

    async def count_all(self, session: AsyncSession) -> int:
        return (await session.execute(select(func.count()).select_from(DataSourceDb))).scalar_one()
