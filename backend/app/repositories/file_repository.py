"""File repository."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_source import DataSourceFile


class FileRepository:
    async def get_by_id(self, session: AsyncSession, id: uuid.UUID) -> DataSourceFile | None:
        return await session.get(DataSourceFile, id)

    async def list(
        self,
        session: AsyncSession,
        *,
        search: str | None = None,
        file_type: str | None = None,
        status: str | None = None,
        storage_backend: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[DataSourceFile], int]:
        stmt = select(DataSourceFile)
        count_stmt = select(func.count()).select_from(DataSourceFile)
        if search:
            filt = DataSourceFile.name.ilike(f"%{search}%")
            stmt = stmt.where(filt)
            count_stmt = count_stmt.where(filt)
        if file_type:
            stmt = stmt.where(DataSourceFile.file_type == file_type)
            count_stmt = count_stmt.where(DataSourceFile.file_type == file_type)
        if status:
            stmt = stmt.where(DataSourceFile.status == status)
            count_stmt = count_stmt.where(DataSourceFile.status == status)
        if storage_backend:
            stmt = stmt.where(DataSourceFile.storage_backend == storage_backend)
            count_stmt = count_stmt.where(DataSourceFile.storage_backend == storage_backend)
        total = (await session.execute(count_stmt)).scalar_one()
        stmt = (
            stmt.order_by(DataSourceFile.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list((await session.execute(stmt)).scalars().all()), total

    async def list_by_ids(
        self, session: AsyncSession, ids: list[uuid.UUID]
    ) -> list[DataSourceFile]:
        if not ids:
            return []
        result = await session.execute(select(DataSourceFile).where(DataSourceFile.id.in_(ids)))
        return list(result.scalars().all())

    async def create(self, session: AsyncSession, obj: DataSourceFile) -> DataSourceFile:
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return obj

    async def update(self, session: AsyncSession, obj: DataSourceFile) -> DataSourceFile:
        await session.flush()
        await session.refresh(obj)
        return obj

    async def delete(self, session: AsyncSession, obj: DataSourceFile) -> None:
        await session.delete(obj)
        await session.flush()

    async def count_ready(self, session: AsyncSession) -> int:
        result = await session.execute(
            select(func.count())
            .select_from(DataSourceFile)
            .where(DataSourceFile.status == "ready")
        )
        return result.scalar_one()

    async def count_all(self, session: AsyncSession) -> int:
        return (
            await session.execute(select(func.count()).select_from(DataSourceFile))
        ).scalar_one()
