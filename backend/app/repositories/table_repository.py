"""Table / column repository."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.data_source import DataSourceTable, DataSourceTableColumn


class TableRepository:
    async def get_by_id(self, session: AsyncSession, id: uuid.UUID) -> DataSourceTable | None:
        result = await session.execute(
            select(DataSourceTable)
            .where(DataSourceTable.id == id)
            .options(selectinload(DataSourceTable.columns))
        )
        return result.scalar_one_or_none()

    async def list_by_source(
        self, session: AsyncSession, data_source_id: uuid.UUID
    ) -> list[DataSourceTable]:
        result = await session.execute(
            select(DataSourceTable)
            .where(DataSourceTable.data_source_id == data_source_id)
            .options(selectinload(DataSourceTable.columns))
            .order_by(DataSourceTable.table_schema, DataSourceTable.table_name)
        )
        return list(result.scalars().all())

    async def delete_by_source(self, session: AsyncSession, data_source_id: uuid.UUID) -> None:
        await session.execute(
            delete(DataSourceTable).where(DataSourceTable.data_source_id == data_source_id)
        )
        await session.flush()

    async def create(self, session: AsyncSession, obj: DataSourceTable) -> DataSourceTable:
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return obj

    async def bulk_create_tables(
        self, session: AsyncSession, tables: list[DataSourceTable]
    ) -> list[DataSourceTable]:
        session.add_all(tables)
        await session.flush()
        return tables

    async def bulk_create_columns(
        self, session: AsyncSession, columns: list[DataSourceTableColumn]
    ) -> None:
        session.add_all(columns)
        await session.flush()

    async def update_selection(
        self,
        session: AsyncSession,
        data_source_id: uuid.UUID,
        selected_ids: set[uuid.UUID],
    ) -> list[DataSourceTable]:
        tables = await self.list_by_source(session, data_source_id)
        for t in tables:
            t.selected_for_modeling = t.id in selected_ids
        await session.flush()
        return tables
