"""FileService — upload, parse, MD convert, build-table stubs (§5.2 / §8.2)."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ErrorCode
from app.db.session import AsyncSessionLocal
from app.models.data_source import DataSourceFile, DataSourceTable, DataSourceTableColumn
from app.repositories.db_source_repository import DbSourceRepository
from app.repositories.file_repository import FileRepository
from app.repositories.table_repository import TableRepository
from app.schemas.common import PageResponse
from app.schemas.data_source import (
    BuildTableSqlResponse,
    FilePreview,
    FileRead,
    FileUpdate,
    MaterializeTableRequest,
    TableRead,
)
from app.services._utils import parse_uuid
from app.storage import get_storage

logger = logging.getLogger(__name__)

ALLOWED_TYPES = {
    "pdf", "docx", "doc", "txt", "md", "markdown", "csv", "xlsx", "xls", "html", "htm"
}
MAX_BYTES = 200 * 1024 * 1024

# Legacy Phase-1 fixture markers — must never be used as document text.
_PLACEHOLDER_POLLUTION_MARKERS = (
    "[占位解析文本]",
    "设备编号 GY-01 属于一号产线",
    "一号产线由华能电气供应主变压器",
    "华能电气供应主变压器",
)


def is_placeholder_polluted(text: str | None) -> bool:
    """True if text still contains the old hardcoded demo parse output."""
    if not text:
        return False
    return any(m in text for m in _PLACEHOLDER_POLLUTION_MARKERS)


def _decode_text_bytes(raw: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def extract_text_from_bytes(*, name: str, file_type: str, raw: bytes) -> str:
    """Extract plain text from uploaded bytes. Never injects demo/fixture content."""
    ext = (file_type or Path(name).suffix.lstrip(".")).lower()

    if ext in {"txt", "md", "markdown", "csv", "html", "htm"}:
        return _decode_text_bytes(raw).strip()

    if ext == "pdf":
        try:
            from io import BytesIO

            from pypdf import PdfReader

            reader = PdfReader(BytesIO(raw))
            parts = [(p.extract_text() or "") for p in reader.pages]
            text = "\n".join(parts).strip()
            if text:
                return text
        except Exception as exc:  # noqa: BLE001
            logger.warning("pdf extract failed for %s: %s", name, exc)

    if ext in {"docx"}:
        try:
            from io import BytesIO

            import docx  # python-docx

            document = docx.Document(BytesIO(raw))
            text = "\n".join(p.text for p in document.paragraphs if p.text).strip()
            if text:
                return text
        except Exception as exc:  # noqa: BLE001
            logger.warning("docx extract failed for %s: %s", name, exc)

    # Best-effort for unknown/binary-ish types: readable text only, no fixtures.
    text = _decode_text_bytes(raw).strip()
    if text:
        return text
    raise AppError(
        ErrorCode.FILE_003,
        message=f"无法从文件解析出文本内容（类型: {ext}）。请上传 txt/md/pdf/docx 等可读文档。",
    )


def _to_read(obj: DataSourceFile) -> FileRead:
    return FileRead(
        id=str(obj.id),
        name=obj.name,
        file_type=obj.file_type,
        storage_backend=obj.storage_backend,
        storage_path=obj.storage_path,
        size_bytes=obj.size_bytes,
        status=obj.status,
        error_message=obj.error_message,
        standard_md_path=obj.standard_md_path,
        ontology_md_path=obj.ontology_md_path,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


class FileService:
    def __init__(self) -> None:
        self.repo = FileRepository()
        self.table_repo = TableRepository()
        self.db_repo = DbSourceRepository()

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
    ) -> PageResponse[FileRead]:
        rows, total = await self.repo.list(
            session,
            search=search,
            file_type=file_type,
            status=status,
            storage_backend=storage_backend,
            page=page,
            page_size=page_size,
        )
        return PageResponse(
            items=[_to_read(r) for r in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get(self, session: AsyncSession, id: str) -> FileRead:
        return _to_read(await self._get(session, id))

    async def upload(
        self,
        session: AsyncSession,
        file: UploadFile,
        *,
        storage_backend: str = "local",
    ) -> FileRead:
        name = file.filename or "unnamed"
        ext = Path(name).suffix.lstrip(".").lower() or "txt"
        if ext not in ALLOWED_TYPES:
            raise AppError(ErrorCode.FILE_001, field="file")
        content = await file.read()
        if len(content) > MAX_BYTES:
            raise AppError(ErrorCode.FILE_002, field="file")

        file_id = uuid.uuid4()
        key = f"{file_id}/{name}"
        storage = get_storage(storage_backend)
        await storage.save(key, content, file.content_type or "application/octet-stream")

        obj = DataSourceFile(
            id=file_id,
            name=name,
            file_type=ext,
            storage_backend=storage_backend,
            storage_path=key,
            size_bytes=len(content),
            status="pending",
        )
        obj = await self.repo.create(session, obj)
        await session.commit()  # ensure visible to background task

        asyncio.create_task(self._parse_file(file_id))
        return _to_read(obj)

    async def _parse_file(self, file_id: uuid.UUID) -> None:
        async with AsyncSessionLocal() as session:
            obj = await self.repo.get_by_id(session, file_id)
            if not obj:
                return
            obj.status = "parsing"
            obj.updated_at = datetime.now(timezone.utc)
            await session.commit()
            try:
                storage = get_storage(obj.storage_backend)
                raw = await storage.read(obj.storage_path)
                text = extract_text_from_bytes(
                    name=obj.name, file_type=obj.file_type, raw=raw
                )
                if not text.strip():
                    raise AppError(ErrorCode.FILE_003, message="解析结果为空")
                obj.extracted_text = text
                obj.status = "ready"
                obj.error_message = None
            except AppError as exc:
                logger.warning("parse rejected for %s: %s", file_id, exc.message)
                obj.status = "failed"
                obj.error_message = exc.message
            except Exception as exc:  # noqa: BLE001
                logger.exception("parse failed for %s", file_id)
                obj.status = "failed"
                obj.error_message = str(exc)
            obj.updated_at = datetime.now(timezone.utc)
            await session.commit()

    async def reparse(self, session: AsyncSession, id: str) -> FileRead:
        """Re-run text extraction from stored bytes (clears old placeholder text)."""
        obj = await self._get(session, id)
        asyncio.create_task(self._parse_file(obj.id))
        obj.status = "parsing"
        obj.error_message = None
        obj.updated_at = datetime.now(timezone.utc)
        await self.repo.update(session, obj)
        return _to_read(obj)

    async def ensure_clean_extracted_text(self, session: AsyncSession, obj: DataSourceFile) -> str:
        """Return real document text; re-extract from storage if legacy placeholder detected."""
        text = obj.extracted_text or ""
        if text.strip() and not is_placeholder_polluted(text):
            return text

        storage = get_storage(obj.storage_backend)
        raw = await storage.read(obj.storage_path)
        fresh = extract_text_from_bytes(name=obj.name, file_type=obj.file_type, raw=raw)
        if not fresh.strip():
            raise AppError(ErrorCode.FILE_003, message=f"文件「{obj.name}」解析结果为空")
        if is_placeholder_polluted(fresh):
            raise AppError(
                ErrorCode.FILE_003,
                message=f"文件「{obj.name}」解析结果异常，请重新上传",
            )
        obj.extracted_text = fresh
        obj.status = "ready"
        obj.error_message = None
        obj.updated_at = datetime.now(timezone.utc)
        await self.repo.update(session, obj)
        await session.flush()
        logger.info("cleared placeholder extracted_text for file %s (%s)", obj.id, obj.name)
        return fresh

    async def preview(self, session: AsyncSession, id: str) -> FilePreview:
        obj = await self._get(session, id)
        try:
            text = await self.ensure_clean_extracted_text(session, obj)
        except AppError:
            text = obj.extracted_text or ""
        truncated = len(text) > 2000
        return FilePreview(
            id=str(obj.id),
            name=obj.name,
            status=obj.status,
            preview_text=text[:2000] if text else None,
            truncated=truncated,
        )

    async def download(self, session: AsyncSession, id: str) -> tuple[str, bytes]:
        obj = await self._get(session, id)
        storage = get_storage(obj.storage_backend)
        data = await storage.read(obj.storage_path)
        return obj.name, data

    async def update(self, session: AsyncSession, id: str, body: FileUpdate) -> FileRead:
        obj = await self._get(session, id)
        if body.name is not None:
            obj.name = body.name
        if body.extracted_text is not None:
            obj.extracted_text = body.extracted_text
        obj.updated_at = datetime.now(timezone.utc)
        await self.repo.update(session, obj)
        return _to_read(obj)

    async def convert_standard_md(self, session: AsyncSession, id: str) -> FileRead:
        obj = await self._get(session, id)
        if obj.status != "ready":
            raise AppError(ErrorCode.FILE_003, message="文件尚未解析完成，无法转换")
        md = f"# {obj.name}\n\n{obj.extracted_text or ''}\n"
        key = f"{obj.id}/standard.md"
        storage = get_storage(obj.storage_backend)
        await storage.save(key, md.encode("utf-8"), "text/markdown")
        obj.standard_md_path = key
        obj.updated_at = datetime.now(timezone.utc)
        await self.repo.update(session, obj)
        return _to_read(obj)

    async def convert_ontology_md(self, session: AsyncSession, id: str) -> FileRead:
        obj = await self._get(session, id)
        if not obj.standard_md_path:
            await self.convert_standard_md(session, id)
            obj = await self._get(session, id)
        base = obj.extracted_text or ""
        ontology_md = f"# Ontology Annotated: {obj.name}\n\n{base}\n"
        key = f"{obj.id}/ontology.md"
        storage = get_storage(obj.storage_backend)
        await storage.save(key, ontology_md.encode("utf-8"), "text/markdown")
        obj.ontology_md_path = key
        obj.updated_at = datetime.now(timezone.utc)
        await self.repo.update(session, obj)
        return _to_read(obj)

    async def build_table_sql(self, session: AsyncSession, id: str) -> BuildTableSqlResponse:
        obj = await self._get(session, id)
        slug = re.sub(r"[^a-zA-Z0-9_]+", "_", Path(obj.name).stem).lower() or "generated_table"
        slug = f"doc_{slug}"[:60]
        columns = [
            {"name": "id", "type": "SERIAL PRIMARY KEY"},
            {"name": "title", "type": "VARCHAR(255)"},
            {"name": "content", "type": "TEXT"},
            {"name": "source_file", "type": "VARCHAR(255)"},
        ]
        ddl = (
            f"CREATE TABLE ontomind_generated.{slug} (\n"
            f"  id SERIAL PRIMARY KEY,\n"
            f"  title VARCHAR(255),\n"
            f"  content TEXT,\n"
            f"  source_file VARCHAR(255)\n"
            f");"
        )
        return BuildTableSqlResponse(ddl=ddl, suggested_table_name=slug, columns=columns)

    async def materialize_table(
        self, session: AsyncSession, id: str, body: MaterializeTableRequest
    ) -> TableRead:
        obj = await self._get(session, id)
        preview = await self.build_table_sql(session, id)
        table_name = body.table_name or preview.suggested_table_name

        # Prefer explicit data_source_id; else first connected source; else stub without FK fail
        data_source_id = None
        if body.data_source_id:
            data_source_id = parse_uuid(body.data_source_id)
        else:
            sources, _ = await self.db_repo.list(session, page=1, page_size=1, status="connected")
            if not sources:
                sources, _ = await self.db_repo.list(session, page=1, page_size=1)
            if sources:
                data_source_id = sources[0].id
        if not data_source_id:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                message="请先创建数据库连接后再物化生成表",
            )

        table = DataSourceTable(
            data_source_id=data_source_id,
            table_schema="ontomind_generated",
            table_name=table_name,
            column_count=4,
            selected_for_modeling=True,
            is_generated=True,
            row_count=0,
        )
        table = await self.table_repo.create(session, table)
        cols = [
            DataSourceTableColumn(
                table_id=table.id, column_name="id", data_type="integer", is_primary_key=True, ordinal=0
            ),
            DataSourceTableColumn(
                table_id=table.id, column_name="title", data_type="varchar", ordinal=1
            ),
            DataSourceTableColumn(
                table_id=table.id, column_name="content", data_type="text", ordinal=2
            ),
            DataSourceTableColumn(
                table_id=table.id, column_name="source_file", data_type="varchar", ordinal=3
            ),
        ]
        await self.table_repo.bulk_create_columns(session, cols)
        table = await self.table_repo.get_by_id(session, table.id)
        assert table is not None
        from app.services.db_source_service import DbSourceService

        return DbSourceService._table_read(table)

    async def delete(self, session: AsyncSession, id: str) -> None:
        obj = await self._get(session, id)
        try:
            storage = get_storage(obj.storage_backend)
            await storage.delete(obj.storage_path)
        except Exception:  # noqa: BLE001
            logger.warning("storage delete failed for %s", id)
        await self.repo.delete(session, obj)

    async def _get(self, session: AsyncSession, id: str) -> DataSourceFile:
        obj = await self.repo.get_by_id(session, parse_uuid(id))
        if not obj:
            raise AppError(ErrorCode.NOT_FOUND, message="文件不存在")
        return obj
