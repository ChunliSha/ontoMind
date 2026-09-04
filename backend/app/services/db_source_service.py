"""DbSourceService — connection CRUD, test, reflect (§5.3 / §8.1)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ErrorCode
from app.core.security import decrypt_password, encrypt_password
from app.models.data_source import DataSourceDb, DataSourceTable, DataSourceTableColumn
from app.repositories.db_source_repository import DbSourceRepository
from app.repositories.table_repository import TableRepository
from app.schemas.common import PageResponse
from app.schemas.data_source import (
    ConnectionTestResult,
    DbSourceCreate,
    DbSourceRead,
    DbSourceUpdate,
    TableColumnRead,
    TableRead,
    TableSelectionPatch,
)
from app.services._utils import parse_uuid

logger = logging.getLogger(__name__)

_TABLES_SQL = """
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_type = 'BASE TABLE'
  AND table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
ORDER BY table_schema, table_name
"""

_COLUMNS_SQL = """
SELECT c.column_name, c.data_type, c.ordinal_position,
       CASE WHEN tc.constraint_type = 'PRIMARY KEY' THEN true ELSE false END AS is_pk
FROM information_schema.columns c
LEFT JOIN information_schema.key_column_usage kcu
  ON c.table_schema = kcu.table_schema
 AND c.table_name = kcu.table_name
 AND c.column_name = kcu.column_name
LEFT JOIN information_schema.table_constraints tc
  ON kcu.constraint_name = tc.constraint_name
 AND kcu.table_schema = tc.table_schema
 AND tc.constraint_type = 'PRIMARY KEY'
WHERE c.table_schema = $1 AND c.table_name = $2
ORDER BY c.ordinal_position
"""


def _column_meta(col) -> dict:
    return {
        "name": col["column_name"],
        "type": col["data_type"],
        "pk": bool(col["is_pk"]),
        "ordinal": int(col["ordinal_position"] or 0),
    }


def _to_read(obj: DataSourceDb) -> DbSourceRead:
    return DbSourceRead(
        id=str(obj.id),
        name=obj.name,
        db_type=obj.db_type,
        host=obj.host,
        port=obj.port,
        database_name=obj.database_name,
        username=obj.username,
        status=obj.status,
        last_error=obj.last_error,
        table_count=obj.table_count or 0,
        last_synced_at=obj.last_synced_at,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


class DbSourceService:
    def __init__(self) -> None:
        self.repo = DbSourceRepository()
        self.table_repo = TableRepository()

    async def list(
        self,
        session: AsyncSession,
        *,
        search: str | None = None,
        db_type: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> PageResponse[DbSourceRead]:
        rows, total = await self.repo.list(
            session, search=search, db_type=db_type, status=status, page=page, page_size=page_size
        )
        return PageResponse(
            items=[_to_read(r) for r in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def create(self, session: AsyncSession, body: DbSourceCreate) -> DbSourceRead:
        existing = await self.repo.get_by_name(session, body.name)
        if existing:
            raise AppError(ErrorCode.DB_SOURCE_002, field="name")
        obj = DataSourceDb(
            name=body.name,
            db_type=body.db_type,
            host=body.host,
            port=body.port,
            database_name=body.database_name,
            username=body.username,
            password_enc=encrypt_password(body.password),
            status="pending",
        )
        obj = await self.repo.create(session, obj)
        try:
            await self._test_and_reflect(session, obj)
        except AppError as exc:
            obj.status = "failed"
            obj.last_error = exc.message
            await self.repo.update(session, obj)
        return _to_read(obj)

    async def update(
        self, session: AsyncSession, id: str, body: DbSourceUpdate
    ) -> DbSourceRead:
        obj = await self._get(session, id)
        data = body.model_dump(exclude_unset=True)
        if "password" in data:
            pwd = data.pop("password")
            if pwd is not None:
                obj.password_enc = encrypt_password(pwd)
        if "name" in data and data["name"] and data["name"] != obj.name:
            clash = await self.repo.get_by_name(session, data["name"])
            if clash:
                raise AppError(ErrorCode.DB_SOURCE_002, field="name")
        for k, v in data.items():
            setattr(obj, k, v)
        if obj.status == "failed":
            obj.status = "pending"
            obj.last_error = None
        obj.updated_at = datetime.now(timezone.utc)
        await self.repo.update(session, obj)
        return _to_read(obj)

    async def delete(self, session: AsyncSession, id: str) -> None:
        obj = await self._get(session, id)
        await self.repo.delete(session, obj)

    async def test_connection(self, session: AsyncSession, id: str) -> ConnectionTestResult:
        obj = await self._get(session, id)
        try:
            await self._test_and_reflect(session, obj)
        except AppError as exc:
            obj.status = "failed"
            obj.last_error = exc.message
            await self.repo.update(session, obj)
            return ConnectionTestResult(ok=False, message=exc.message)
        return ConnectionTestResult(
            ok=True,
            message="连接成功",
            table_count=obj.table_count or 0,
        )

    async def test_draft(self, body: DbSourceCreate) -> ConnectionTestResult:
        """测试尚未落库的连接参数（表单内「测试连接」）。"""
        if body.db_type not in ("postgres", "gaussdb"):
            return ConnectionTestResult(
                ok=False,
                message=f"MVP 阶段仅支持 postgres/gaussdb（当前: {body.db_type}）",
            )
        import asyncpg

        try:
            conn = await asyncpg.connect(
                host=body.host,
                port=body.port,
                user=body.username,
                password=body.password,
                database=body.database_name,
                timeout=8,
            )
            try:
                await conn.fetchval("SELECT 1")
                table_count = await conn.fetchval(
                    """
                    SELECT COUNT(*)::int
                    FROM information_schema.tables
                    WHERE table_type = 'BASE TABLE'
                      AND table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
                    """
                )
            finally:
                await conn.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("draft db connection test failed: %s", exc)
            return ConnectionTestResult(
                ok=False,
                message="连接失败，请检查主机地址与端口",
            )
        return ConnectionTestResult(
            ok=True,
            message="连接成功",
            table_count=int(table_count or 0),
        )

    async def list_tables(self, session: AsyncSession, id: str) -> list[TableRead]:
        obj = await self._get(session, id)
        obj.status = "syncing"
        await self.repo.update(session, obj)
        try:
            await self._reflect(session, obj)
            obj.status = "connected"
            obj.last_synced_at = datetime.now(timezone.utc)
            obj.last_error = None
            await self.repo.update(session, obj)
        except AppError:
            obj.status = "failed"
            await self.repo.update(session, obj)
            raise
        tables = await self.table_repo.list_by_source(session, obj.id)
        return [self._table_read(t) for t in tables]

    async def patch_selection(
        self, session: AsyncSession, id: str, body: TableSelectionPatch
    ) -> list[TableRead]:
        obj = await self._get(session, id)
        selected = {parse_uuid(x) for x in body.selected_table_ids}
        tables = await self.table_repo.update_selection(session, obj.id, selected)
        return [self._table_read(t) for t in tables]

    async def _get(self, session: AsyncSession, id: str) -> DataSourceDb:
        obj = await self.repo.get_by_id(session, parse_uuid(id))
        if not obj:
            raise AppError(ErrorCode.NOT_FOUND, message="数据库连接不存在")
        return obj

    async def _connect(self, obj: DataSourceDb):
        if obj.db_type not in ("postgres", "gaussdb"):
            raise AppError(
                ErrorCode.DB_SOURCE_001,
                message=f"MVP 阶段仅支持 postgres/gaussdb 反射（当前: {obj.db_type}）",
            )
        import asyncpg

        password = decrypt_password(obj.password_enc)
        try:
            return await asyncpg.connect(
                host=obj.host,
                port=obj.port,
                user=obj.username,
                password=password,
                database=obj.database_name,
                timeout=8,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("db connection test failed: %s", exc)
            raise AppError(ErrorCode.DB_SOURCE_001) from exc

    async def _test_and_reflect(self, session: AsyncSession, obj: DataSourceDb) -> None:
        conn = await self._connect(obj)
        try:
            await conn.fetchval("SELECT 1")
        finally:
            await conn.close()
        obj.status = "connected"
        obj.last_error = None
        await self.repo.update(session, obj)
        try:
            await self._reflect(session, obj)
        except Exception:  # noqa: BLE001
            logger.exception("reflect failed after successful ping")

    async def _reflect(self, session: AsyncSession, obj: DataSourceDb) -> None:
        conn = await self._connect(obj)
        try:
            meta = await self._fetch_table_meta(conn)
        except Exception as exc:  # noqa: BLE001
            raise AppError(ErrorCode.DB_SOURCE_001, message=f"反射表结构失败: {exc}") from exc
        finally:
            await conn.close()
        await self._upsert_reflected_tables(session, obj, meta)

    @staticmethod
    async def _fetch_table_meta(conn) -> list[dict]:
        tables = await conn.fetch(_TABLES_SQL)
        meta: list[dict] = []
        for table in tables:
            schema_name, table_name = table["table_schema"], table["table_name"]
            cols = await conn.fetch(_COLUMNS_SQL, schema_name, table_name)
            meta.append(
                {
                    "schema": schema_name,
                    "name": table_name,
                    "columns": [_column_meta(col) for col in cols],
                }
            )
        return meta

    async def _upsert_reflected_tables(self, session, obj, meta) -> None:
        old = await self.table_repo.list_by_source(session, obj.id)
        by_key = {(t.table_schema, t.table_name): t for t in old}
        seen: set[tuple[str, str]] = set()

        for item in meta:
            key = (item["schema"], item["name"])
            seen.add(key)
            existing = by_key.get(key)
            if existing:
                table = existing
                table.column_count = len(item["columns"])
                # Keep selected_for_modeling / id stable so field mappings survive re-sync.
                await self.table_repo.delete_columns(session, table.id)
            else:
                table = DataSourceTable(
                    data_source_id=obj.id,
                    table_schema=item["schema"],
                    table_name=item["name"],
                    column_count=len(item["columns"]),
                    selected_for_modeling=False,
                    is_generated=False,
                )
                await self.table_repo.create(session, table)

            cols = [
                DataSourceTableColumn(
                    table_id=table.id,
                    column_name=c["name"],
                    data_type=c["type"],
                    is_primary_key=c["pk"],
                    ordinal=c["ordinal"],
                )
                for c in item["columns"]
            ]
            await self.table_repo.bulk_create_columns(session, cols)

        for key, table in by_key.items():
            if key not in seen:
                await self.table_repo.delete(session, table)

        obj.table_count = len(meta)
        obj.last_synced_at = datetime.now(timezone.utc)
        await self.repo.update(session, obj)

    @staticmethod
    def _table_read(t: DataSourceTable) -> TableRead:
        return TableRead(
            id=str(t.id),
            table_schema=t.table_schema,
            table_name=t.table_name,
            row_count=t.row_count,
            column_count=t.column_count,
            selected_for_modeling=t.selected_for_modeling,
            is_generated=t.is_generated,
            columns=[
                TableColumnRead(
                    id=str(c.id),
                    column_name=c.column_name,
                    data_type=c.data_type,
                    is_primary_key=c.is_primary_key,
                    ordinal=c.ordinal,
                )
                for c in (t.columns or [])
            ],
        )
