"""ExtractionService — all 4 async task types (§5.1 / §8.4 / §9.5 / §10)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ErrorCode
from app.models.extraction import ExtractionTask
from app.repositories.class_repository import ClassRepository
from app.repositories.db_source_repository import DbSourceRepository
from app.repositories.file_repository import FileRepository
from app.repositories.instance_relation_repository import InstanceRelationRepository
from app.repositories.instance_repository import InstanceRepository
from app.repositories.mapping_repository import MappingRepository
from app.repositories.property_repository import PropertyRepository
from app.repositories.schema_repository import SchemaRepository
from app.repositories.table_repository import TableRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.common import PageResponse
from app.schemas.extraction import (
    BusinessLogicExtractionRequest,
    ClearInstancesRequest,
    ClearInstancesResult,
    ExtractionTaskRead,
    InstanceInventoryResponse,
    InstanceRead,
    InstanceStatsItem,
    InstanceStatsResponse,
    StructuredExtractionRequest,
    TaskAccepted,
    UnstructuredExtractionRequest,
)
from app.schemas.schema import SchemaInduceRequest
from app.services._utils import parse_uuid, uid
from app.services.extraction_tasks import ExtractionTaskMixin
from app.services.file_service import FileService
from app.tasks import runner

logger = logging.getLogger(__name__)


def _task_read(obj: ExtractionTask) -> ExtractionTaskRead:
    return ExtractionTaskRead(
        id=str(obj.id),
        task_type=obj.task_type,
        status=obj.status,
        schema_id=uid(obj.schema_id),
        progress=float(obj.progress or 0),
        output_summary=obj.output_summary,
        error_message=obj.error_message,
        created_at=obj.created_at,
        started_at=obj.started_at,
        finished_at=obj.finished_at,
    )


class ExtractionService(ExtractionTaskMixin):
    def __init__(self) -> None:
        self.task_repo = TaskRepository()
        self.schema_repo = SchemaRepository()
        self.class_repo = ClassRepository()
        self.prop_repo = PropertyRepository()
        self.file_repo = FileRepository()
        self.file_svc = FileService()
        self.instance_repo = InstanceRepository()
        self.relation_repo = InstanceRelationRepository()
        self.mapping_repo = MappingRepository()
        self.table_repo = TableRepository()
        self.db_repo = DbSourceRepository()

    async def induce_schema(
        self, session: AsyncSession, schema_id: str, body: SchemaInduceRequest
    ) -> TaskAccepted:
        sid = parse_uuid(schema_id)
        schema = await self.schema_repo.get_by_id(session, sid)
        if not schema:
            raise AppError(ErrorCode.GRAPH_001)
        files = await self.file_repo.list_by_ids(session, [parse_uuid(item) for item in body.file_ids])
        ready = [file_obj for file_obj in files if file_obj.status == "ready"]
        if not ready:
            raise AppError(ErrorCode.FILE_004)
        existing = await self._adopt_or_clear_running(
            session, task_type="schema_induction", schema_id=sid
        )
        if existing:
            return TaskAccepted(task_id=str(existing))
        task = ExtractionTask(
            task_type="schema_induction",
            status="pending",
            schema_id=sid,
            input={
                "file_ids": body.file_ids,
                "ai_config": body.ai_config,
                "model_id": body.model_id,
            },
        )
        task = await self.task_repo.create(session, task)
        await session.commit()
        runner.spawn(task.id, self._run_schema_induction)
        return TaskAccepted(task_id=str(task.id))

    async def run_unstructured(
        self, session: AsyncSession, body: UnstructuredExtractionRequest
    ) -> TaskAccepted:
        sid = parse_uuid(body.schema_id)
        schema = await self.schema_repo.get_by_id(session, sid)
        if not schema:
            raise AppError(ErrorCode.GRAPH_001)
        class_count = await self.class_repo.count_by_schema(session, sid)
        if class_count < 1:
            raise AppError(ErrorCode.SCHEMA_005)
        files = await self.file_repo.list_by_ids(session, [parse_uuid(item) for item in body.file_ids])
        ready = [file_obj for file_obj in files if file_obj.status == "ready"]
        if not ready:
            raise AppError(ErrorCode.FILE_004)
        existing = await self._adopt_or_clear_running(
            session, task_type="instance_unstructured", schema_id=sid
        )
        if existing:
            await self._supersede_running(session, existing)
        task = ExtractionTask(
            task_type="instance_unstructured",
            status="pending",
            schema_id=sid,
            input={
                "file_ids": body.file_ids,
                "ai_config": body.ai_config,
                "model_id": body.model_id,
                "replace_existing": body.replace_existing,
                "schema_version": schema.version,
            },
        )
        task = await self.task_repo.create(session, task)
        await session.commit()
        runner.spawn(task.id, self._run_unstructured)
        return TaskAccepted(task_id=str(task.id))

    async def run_structured(
        self, session: AsyncSession, body: StructuredExtractionRequest
    ) -> TaskAccepted:
        sid = parse_uuid(body.schema_id)
        schema = await self.schema_repo.get_by_id(session, sid)
        if not schema:
            raise AppError(ErrorCode.GRAPH_001)
        for mapping_id in body.mapping_ids:
            await self._require_mapping(session, mapping_id, sid)
        existing = await self._adopt_or_clear_running(
            session, task_type="instance_structured", schema_id=sid
        )
        if existing:
            await self._supersede_running(session, existing)
        task = ExtractionTask(
            task_type="instance_structured",
            status="pending",
            schema_id=sid,
            input={"mapping_ids": body.mapping_ids},
        )
        task = await self.task_repo.create(session, task)
        await session.commit()
        runner.spawn(task.id, self._run_structured)
        return TaskAccepted(task_id=str(task.id))

    async def run_business_logic(
        self, session: AsyncSession, body: BusinessLogicExtractionRequest
    ) -> TaskAccepted:
        sid, version, ontology_model_id = await self._resolve_logic_schema(session, body)
        schema = await self.schema_repo.get_by_id(session, sid)
        if not schema:
            raise AppError(ErrorCode.GRAPH_001)
        inst_count = await self.instance_repo.count_by_schema(
            session, sid, schema_version=version
        )
        if inst_count < 1:
            raise AppError(ErrorCode.BIZLOGIC_001)
        files = await self.file_repo.list_by_ids(session, [parse_uuid(item) for item in body.file_ids])
        ready = [file_obj for file_obj in files if file_obj.status == "ready"]
        if not ready:
            raise AppError(ErrorCode.FILE_004)
        existing = await self._adopt_or_clear_running(
            session, task_type="business_logic_topology", schema_id=sid
        )
        if not existing:
            existing = await self._adopt_or_clear_running(
                session, task_type="business_logic", schema_id=sid
            )
        if existing:
            return TaskAccepted(task_id=str(existing))
        task = ExtractionTask(
            task_type="business_logic_topology",
            status="pending",
            schema_id=sid,
            input={
                "file_ids": body.file_ids,
                "ai_config": body.ai_config,
                "model_id": body.model_id,
                "schema_version": version,
                "type_mapping": body.type_mapping,
                "name": body.name,
                "ontology_model_id": str(ontology_model_id) if ontology_model_id else None,
            },
        )
        task = await self.task_repo.create(session, task)
        await session.commit()
        runner.spawn(task.id, self._run_business_logic)
        return TaskAccepted(task_id=str(task.id))

    async def get_task(self, session: AsyncSession, id: str) -> ExtractionTaskRead:
        obj = await self.task_repo.get_by_id(session, parse_uuid(id))
        if not obj:
            raise AppError(ErrorCode.TASK_001)
        if obj.status in ("pending", "running") and not runner.is_alive(obj.id):
            self._mark_orphan_failed(obj)
            await session.commit()
        return _task_read(obj)

    async def cancel_task(self, session: AsyncSession, id: str) -> ExtractionTaskRead:
        obj = await self.task_repo.get_by_id(session, parse_uuid(id))
        if not obj:
            raise AppError(ErrorCode.TASK_001)
        if obj.status not in ("pending", "running"):
            return _task_read(obj)
        runner.request_cancel(obj.id)
        obj.status = "failed"
        obj.error_message = runner.CANCEL_MESSAGE
        obj.finished_at = datetime.now(timezone.utc)
        await session.commit()
        return _task_read(obj)

    async def list_tasks(
        self,
        session: AsyncSession,
        *,
        task_type: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[ExtractionTaskRead]:
        statuses: list[str] | None = None
        if status in ("active", "running"):
            statuses = ["pending", "running"]
        elif status:
            statuses = [status]
        rows = await self.task_repo.list_by_schema(
            session, task_type=task_type, status=statuses, limit=limit
        )
        live: list[ExtractionTask] = []
        dirty = False
        only_active = bool(statuses) and set(statuses) <= {"pending", "running"}
        for row in rows:
            stale = row.status in ("pending", "running") and not runner.is_alive(row.id)
            if stale:
                self._mark_orphan_failed(row)
                dirty = True
                if only_active:
                    continue
            live.append(row)
        if dirty:
            await session.commit()
        return [_task_read(row) for row in live]

    async def list_task_instances(
        self, session: AsyncSession, task_id: str, *, page: int = 1, page_size: int = 20
    ) -> PageResponse[InstanceRead]:
        tid = parse_uuid(task_id)
        task = await self.task_repo.get_by_id(session, tid)
        if not task:
            raise AppError(ErrorCode.TASK_001)
        rows, total = await self.instance_repo.list_by_task(
            session, tid, page=page, page_size=page_size
        )
        items = [await self._instance_summary(session, row) for row in rows]
        return PageResponse(items=items, total=total, page=page, page_size=page_size)

    async def get_instance(self, session: AsyncSession, id: str) -> InstanceRead:
        obj = await self.instance_repo.get_by_id(session, parse_uuid(id))
        if not obj:
            raise AppError(ErrorCode.NOT_FOUND, message="实例不存在")
        return await self._instance_detail(session, obj)

    async def list_schema_instances(
        self,
        session: AsyncSession,
        schema_id: str,
        *,
        schema_version: int | None = None,
        class_id: str | None = None,
        source_type: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> PageResponse[InstanceRead]:
        sid = parse_uuid(schema_id)
        schema = await self.schema_repo.get_by_id(session, sid)
        if not schema:
            raise AppError(ErrorCode.GRAPH_001)
        rows, total = await self.instance_repo.list_page(
            session,
            sid,
            schema_version=schema_version,
            class_id=parse_uuid(class_id) if class_id else None,
            source_type=source_type,
            page=page,
            page_size=page_size,
        )
        items = [await self._instance_summary(session, row) for row in rows]
        return PageResponse(items=items, total=total, page=page, page_size=page_size)

    async def instance_inventory(
        self,
        session: AsyncSession,
        schema_id: str,
        *,
        schema_version: int | None = None,
    ) -> InstanceInventoryResponse:
        sid = parse_uuid(schema_id)
        schema = await self.schema_repo.get_by_id(session, sid)
        if not schema:
            raise AppError(ErrorCode.GRAPH_001)
        filter_ver = schema_version if schema_version is not None else schema.version
        versions = await self.instance_repo.list_versions(session, sid)
        if schema.version not in versions:
            versions = [schema.version, *versions]
        rows = await self.instance_repo.count_by_class(
            session, sid, schema_version=filter_ver
        )
        by_class = [
            InstanceStatsItem(class_id=str(cid), class_label=label, count=cnt)
            for cid, label, cnt in rows
            if cnt > 0
        ]
        uncategorized = await self.instance_repo.count_null_class(
            session, sid, schema_version=filter_ver
        )
        if uncategorized:
            by_class.append(
                InstanceStatsItem(class_id="", class_label="未分类", count=uncategorized)
            )
        total = sum(item.count for item in by_class)
        tasks = await self.task_repo.list_by_schema(
            session,
            schema_id=sid,
            task_type="instance_unstructured",
            limit=10,
        )
        return InstanceInventoryResponse(
            schema_id=str(sid),
            schema_name=schema.name,
            schema_version=schema.version,
            filter_version=filter_ver,
            versions=versions,
            total=total,
            by_class=by_class,
            recent_tasks=[_task_read(task) for task in tasks],
        )

    async def clear_schema_instances(
        self,
        session: AsyncSession,
        schema_id: str,
        body: ClearInstancesRequest | None = None,
    ) -> ClearInstancesResult:
        sid = parse_uuid(schema_id)
        schema = await self.schema_repo.get_by_id(session, sid)
        if not schema:
            raise AppError(ErrorCode.GRAPH_001)
        body = body or ClearInstancesRequest()
        version = body.schema_version if body.schema_version is not None else schema.version
        deleted = await self.instance_repo.delete_by_schema(
            session,
            sid,
            schema_version=version,
            source_types=body.source_types,
        )
        await self.schema_repo.invalidate_graph_cache(session, sid)
        await session.commit()
        return ClearInstancesResult(
            deleted=deleted, schema_id=str(sid), schema_version=version
        )

    async def instance_stats(
        self,
        session: AsyncSession,
        schema_id: str,
        *,
        schema_version: int | None = None,
    ) -> InstanceStatsResponse:
        sid = parse_uuid(schema_id)
        rows = await self.instance_repo.count_by_class(
            session, sid, schema_version=schema_version
        )
        by_class = [
            InstanceStatsItem(class_id=str(cid), class_label=label, count=cnt)
            for cid, label, cnt in rows
        ]
        uncategorized = await self.instance_repo.count_null_class(
            session, sid, schema_version=schema_version
        )
        if uncategorized:
            by_class.append(
                InstanceStatsItem(class_id="", class_label="未分类", count=uncategorized)
            )
        total = sum(item.count for item in by_class)
        return InstanceStatsResponse(
            schema_id=schema_id,
            schema_version=schema_version,
            total=total,
            by_class=by_class,
        )
