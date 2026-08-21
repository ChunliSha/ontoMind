"""ExtractionService — all 4 async task types (§5.1 / §8.4 / §9.5 / §10)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.ai import resolve_llm_provider
from app.ai.base import SchemaSnapshot, SchemaSnapshotClass, SchemaSnapshotProperty
from app.core.exceptions import AppError, ErrorCode
from app.core.security import decrypt_password
from app.db.session import session_scope
from app.models.extraction import ExtractionTask
from app.models.instance import InstanceDataValue, InstanceRelation, OntologyInstance
from app.models.schema import OntologyClass, OntologyProperty
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
from app.rdf.ttl_builder import label_to_local_name
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
from app.services.file_service import FileService
from app.tasks import runner

logger = logging.getLogger(__name__)


def _task_read(obj: ExtractionTask) -> ExtractionTaskRead:
    return ExtractionTaskRead(
        id=str(obj.id),
        task_type=obj.task_type,  # type: ignore[arg-type]
        status=obj.status,  # type: ignore[arg-type]
        schema_id=uid(obj.schema_id),
        progress=float(obj.progress or 0),
        output_summary=obj.output_summary,
        error_message=obj.error_message,
        created_at=obj.created_at,
        started_at=obj.started_at,
        finished_at=obj.finished_at,
    )


class ExtractionService:
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

    async def _adopt_or_clear_running(
        self,
        session: AsyncSession,
        *,
        task_type: str,
        schema_id: uuid.UUID | None,
    ) -> uuid.UUID | None:
        """Reuse a live in-process job, or fail a stale DB row left by a restart."""
        running = await self.task_repo.find_running(
            session, task_type=task_type, schema_id=schema_id
        )
        if not running:
            return None
        if runner.is_alive(running.id):
            return running.id
        self._mark_orphan_failed(running)
        await session.flush()
        return None

    async def _supersede_running(self, session: AsyncSession, task_id: uuid.UUID) -> None:
        """Stop a live job so a newly requested extraction can start cleanly."""
        runner.request_cancel(task_id)
        row = await self.task_repo.get_by_id(session, task_id)
        if row and row.status in ("pending", "running"):
            row.status = "failed"
            row.error_message = runner.CANCEL_MESSAGE
            row.finished_at = datetime.now(timezone.utc)
            await session.flush()

    def _mark_orphan_failed(self, task: ExtractionTask) -> None:
        task.status = "failed"
        task.error_message = "任务进程已丢失，已自动中断"
        task.finished_at = datetime.now(timezone.utc)

    async def _llm_for_task(self, session: AsyncSession, task: ExtractionTask):
        model_id = (task.input or {}).get("model_id")
        return await resolve_llm_provider(session, model_id)

    async def _load_file_text(self, session: AsyncSession, f) -> str:
        """Load document text for AI; never use legacy placeholder fixtures."""
        # Prefer ontology_md only when it itself is not polluted placeholder.
        if f.ontology_md_path:
            from app.storage import get_storage

            try:
                raw = await get_storage(f.storage_backend).read(f.ontology_md_path)
                md = raw.decode("utf-8", errors="ignore")
                from app.services.file_service import is_placeholder_polluted

                if md.strip() and not is_placeholder_polluted(md):
                    return md
            except Exception:  # noqa: BLE001
                pass
        return await self.file_svc.ensure_clean_extracted_text(session, f)

    async def induce_schema(
        self, session: AsyncSession, schema_id: str, body: SchemaInduceRequest
    ) -> TaskAccepted:
        sid = parse_uuid(schema_id)
        schema = await self.schema_repo.get_by_id(session, sid)
        if not schema:
            raise AppError(ErrorCode.GRAPH_001)
        files = await self.file_repo.list_by_ids(session, [parse_uuid(x) for x in body.file_ids])
        ready = [f for f in files if f.status == "ready"]
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
        tid = task.id
        runner.spawn(tid, self._run_schema_induction)
        return TaskAccepted(task_id=str(tid))

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
        files = await self.file_repo.list_by_ids(session, [parse_uuid(x) for x in body.file_ids])
        ready = [f for f in files if f.status == "ready"]
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
        tid = task.id
        runner.spawn(tid, self._run_unstructured)
        return TaskAccepted(task_id=str(tid))

    async def run_structured(
        self, session: AsyncSession, body: StructuredExtractionRequest
    ) -> TaskAccepted:
        sid = parse_uuid(body.schema_id)
        schema = await self.schema_repo.get_by_id(session, sid)
        if not schema:
            raise AppError(ErrorCode.GRAPH_001)
        mappings = []
        for mid in body.mapping_ids:
            m = await self.mapping_repo.get_by_id(session, parse_uuid(mid))
            if not m:
                raise AppError(
                    ErrorCode.NOT_FOUND,
                    message="所选字段映射不存在或已失效（可能因重新同步表结构被删除），请重新配置并勾选映射",
                )
            if not m.bindings:
                raise AppError(
                    ErrorCode.MAPPING_001,
                    message="所选映射没有字段绑定，请重新配置字段映射",
                )
            if not any(b.target_kind == "instance_uri" for b in m.bindings):
                raise AppError(ErrorCode.MAPPING_001)
            if m.schema_id != sid:
                raise AppError(
                    ErrorCode.MAPPING_001,
                    message="所选映射不属于当前 Schema，请重新勾选",
                )
            mappings.append(m)

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
        tid = task.id
        runner.spawn(tid, self._run_structured)
        return TaskAccepted(task_id=str(tid))

    async def run_business_logic(
        self, session: AsyncSession, body: BusinessLogicExtractionRequest
    ) -> TaskAccepted:
        from app.services.ontology_model_service import OntologyModelService

        om_id = None
        version = body.schema_version
        if body.ontology_model_id:
            om = await OntologyModelService().get_orm(session, body.ontology_model_id)
            sid = om.schema_id
            version = om.schema_version
            om_id = om.id
        else:
            sid = parse_uuid(body.schema_id or "")

        schema = await self.schema_repo.get_by_id(session, sid)
        if not schema:
            raise AppError(ErrorCode.GRAPH_001)
        inst_count = await self.instance_repo.count_by_schema(
            session, sid, schema_version=version
        )
        if inst_count < 1:
            raise AppError(ErrorCode.BIZLOGIC_001)
        files = await self.file_repo.list_by_ids(session, [parse_uuid(x) for x in body.file_ids])
        ready = [f for f in files if f.status == "ready"]
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
                "ontology_model_id": str(om_id) if om_id else None,
            },
        )
        task = await self.task_repo.create(session, task)
        await session.commit()
        tid = task.id
        runner.spawn(tid, self._run_business_logic)
        return TaskAccepted(task_id=str(tid))

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
        for r in rows:
            if r.status in ("pending", "running") and not runner.is_alive(r.id):
                self._mark_orphan_failed(r)
                dirty = True
                if only_active:
                    continue
            live.append(r)
        if dirty:
            await session.commit()
        return [_task_read(r) for r in live]

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
        items = [await self._instance_summary(session, r) for r in rows]
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
        items = [await self._instance_summary(session, r) for r in rows]
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
        total = sum(x.count for x in by_class)
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
            recent_tasks=[_task_read(t) for t in tasks],
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
        total = sum(x.count for x in by_class)
        return InstanceStatsResponse(
            schema_id=schema_id,
            schema_version=schema_version,
            total=total,
            by_class=by_class,
        )

    # ---- background runners ----

    async def _run_schema_induction(self, task_id: uuid.UUID) -> None:
        async with session_scope() as session:
            task = await self.task_repo.get_by_id(session, task_id)
            assert task and task.schema_id
            file_ids = [parse_uuid(x) for x in (task.input or {}).get("file_ids", [])]
            files = await self.file_repo.list_by_ids(session, file_ids)
            texts = []
            for f in files:
                texts.append(await self._load_file_text(session, f))
            existing = [c.label for c in await self.class_repo.list_by_schema(session, task.schema_id)]
            llm = await self._llm_for_task(session, task)
            if not any((t or "").strip() for t in texts):
                raise RuntimeError("所选文档无可抽取文本，请确认文件已解析完成后再抽取")
            result = await llm.induce_schema(texts, existing)
            if not result.success or not result.result:
                raise RuntimeError(result.error or "schema induction failed")
            if not result.result.classes:
                raise RuntimeError("模型未返回任何类，请检查文档内容或更换模型后重试")

            created_c = 0
            created_p = 0
            label_to_class: dict[str, OntologyClass] = {
                c.label: c for c in await self.class_repo.list_by_schema(session, task.schema_id)
            }
            total_steps = max(len(result.result.classes) + len(result.result.properties), 1)
            step = 0
            for ic in result.result.classes:
                if ic.label in label_to_class:
                    continue
                obj = OntologyClass(
                    schema_id=task.schema_id,
                    label=ic.label,
                    local_name=ic.local_name or label_to_local_name(ic.label),
                    description=ic.description,
                    source="ai",
                )
                obj = await self.class_repo.create(session, obj)
                label_to_class[ic.label] = obj
                created_c += 1
                step += 1
                await runner.update_task_progress(task_id, progress=step / total_steps * 100)

            for ip in result.result.properties:
                cls = label_to_class.get(ip.class_label)
                if not cls:
                    continue
                if await self.prop_repo.get_by_label(session, cls.id, ip.label):
                    continue
                range_id = None
                if ip.kind == "object" and ip.range_class_label:
                    rc = label_to_class.get(ip.range_class_label)
                    range_id = rc.id if rc else None
                prop = OntologyProperty(
                    schema_id=task.schema_id,
                    domain_class_id=cls.id,
                    label=ip.label,
                    local_name=label_to_local_name(ip.label),
                    kind=ip.kind,
                    datatype=ip.datatype,
                    range_class_id=range_id,
                    required=ip.required,
                    multi=ip.multi,
                    source="ai",
                    confidence=Decimal(str(ip.confidence or 80)),
                )
                await self.prop_repo.create(session, prop)
                created_p += 1
                step += 1
                await runner.update_task_progress(task_id, progress=min(step / total_steps * 100, 99))

            schema = await self.schema_repo.get_by_id(session, task.schema_id)
            if schema and schema.source == "manual":
                schema.source = "ai_induced"
                schema.updated_at = datetime.now(timezone.utc)
            await self.schema_repo.invalidate_graph_cache(session, task.schema_id)
            await session.commit()
            await runner.update_task_progress(
                task_id,
                status="succeeded",
                progress=100,
                output_summary={"classes_created": created_c, "properties_created": created_p},
            )

    async def _run_unstructured(self, task_id: uuid.UUID) -> None:
        async with session_scope() as session:
            task = await self.task_repo.get_by_id(session, task_id)
            assert task and task.schema_id
            schema = await self.schema_repo.get_by_id(session, task.schema_id)
            assert schema
            schema_version = int(
                (task.input or {}).get("schema_version") or schema.version or 1
            )
            if (task.input or {}).get("replace_existing", True):
                deleted = await self.instance_repo.delete_by_schema(
                    session,
                    task.schema_id,
                    schema_version=schema_version,
                    source_types=["ai_unstructured"],
                )
                if deleted:
                    logger.info(
                        "replaced %s unstructured instances for schema %s v%s",
                        deleted,
                        task.schema_id,
                        schema_version,
                    )
                await session.commit()

            snapshot = await self._schema_snapshot(session, task.schema_id)
            file_ids = [parse_uuid(x) for x in (task.input or {}).get("file_ids", [])]
            files = await self.file_repo.list_by_ids(session, file_ids)
            ok, fail = 0, 0
            total = max(len(files), 1)
            llm = await self._llm_for_task(session, task)
            await runner.update_task_progress(
                task_id,
                progress=3,
                output_summary={"stage": "准备文档与本体，即将调用模型…"},
            )

            # Cross-document merge like extract/map_instances: (class, slug(label)) → one instance
            from app.ai.base import ExtractedInstance
            from app.ai.populate_ontology_pipeline import _instance_merge_key

            merged: dict[tuple[str, str], ExtractedInstance] = {}
            file_names: list[str] = []

            for i, f in enumerate(files):
                if runner.is_cancelled(task_id):
                    raise runner.ExtractionCancelled(runner.CANCEL_MESSAGE)
                try:
                    text_content = await self._load_file_text(session, f)
                    if not text_content.strip():
                        fail += 1
                        await runner.update_task_progress(task_id, progress=(i + 1) / total * 100)
                        continue
                    await runner.update_task_progress(
                        task_id,
                        progress=min(90, 8 + i / total * 80),
                        output_summary={
                            "stage": (
                                f"正在抽取「{f.name}」（{i + 1}/{len(files)}）："
                                "实体识别 → 关系抽取 → 三元组，模型调用可能需要数分钟"
                            ),
                        },
                    )
                    ai = await llm.extract_instances([text_content], snapshot, task_id=task_id)
                    if runner.is_cancelled(task_id):
                        raise runner.ExtractionCancelled(runner.CANCEL_MESSAGE)
                    if not ai.success or not ai.result:
                        fail += 1
                        logger.warning("unstructured extract failed for %s: %s", f.id, ai.error)
                        await runner.update_task_progress(task_id, progress=(i + 1) / total * 100)
                        continue
                    file_names.append(f.name)
                    for inst in ai.result.instances:
                        key = _instance_merge_key(inst.class_label, inst.label)
                        existing = merged.get(key)
                        if existing is None:
                            merged[key] = inst
                        else:
                            if (inst.confidence or 0) > (existing.confidence or 0):
                                existing.confidence = inst.confidence
                            seen_dv = {(d.property_label, d.value) for d in existing.data_values}
                            for d in inst.data_values:
                                if (d.property_label, d.value) not in seen_dv:
                                    existing.data_values.append(d)
                            seen_rel = {
                                (r.property_label, r.target_instance_label)
                                for r in existing.relations
                            }
                            for r in inst.relations:
                                if (r.property_label, r.target_instance_label) not in seen_rel:
                                    existing.relations.append(r)
                    ok += 1
                except runner.ExtractionCancelled:
                    raise
                except Exception:  # noqa: BLE001
                    logger.exception("file %s extraction failed", f.id)
                    fail += 1
                await runner.update_task_progress(task_id, progress=(i + 1) / total * 100)

            if runner.is_cancelled(task_id):
                raise runner.ExtractionCancelled(runner.CANCEL_MESSAGE)
            if merged:
                await self._persist_extracted(
                    session,
                    schema_id=task.schema_id,
                    schema_version=schema_version,
                    task_id=task_id,
                    extracted=list(merged.values()),
                    source_type="ai_unstructured",
                    source_ref={
                        "file_names": file_names,
                        "file_count": len(file_names),
                        "deduped": True,
                    },
                )
            await session.commit()
            await self.schema_repo.invalidate_graph_cache(session, task.schema_id)
            await session.commit()
            await runner.update_task_progress(
                task_id,
                status="succeeded",
                progress=100,
                output_summary={
                    "succeeded": ok,
                    "failed": fail,
                    "schema_version": schema_version,
                    "instances": len(merged),
                },
            )

    async def _run_structured(self, task_id: uuid.UUID) -> None:
        async with session_scope() as session:
            task = await self.task_repo.get_by_id(session, task_id)
            assert task and task.schema_id
            schema = await self.schema_repo.get_by_id(session, task.schema_id)
            if not schema:
                raise RuntimeError("schema not found for structured extraction")
            schema_version = int(schema.version or 1)
            mapping_ids = [parse_uuid(x) for x in (task.input or {}).get("mapping_ids", [])]
            created = 0
            updated = 0
            skipped = 0
            fetch_errors: list[str] = []

            for mi, mid in enumerate(mapping_ids):
                mapping = await self.mapping_repo.get_by_id(session, mid)
                if not mapping:
                    continue
                table = await self.table_repo.get_by_id(session, mapping.table_id)
                if not table:
                    continue
                ds = await self.db_repo.get_by_id(session, table.data_source_id)
                if not ds:
                    continue
                uri_col = next(
                    (b.source_column for b in mapping.bindings if b.target_kind == "instance_uri"),
                    None,
                )
                if not uri_col:
                    raise AppError(ErrorCode.MAPPING_001)
                prop_bindings = [b for b in mapping.bindings if b.target_kind == "property"]
                props = {
                    b.target_property_id: await self.prop_repo.get_by_id(session, b.target_property_id)
                    for b in prop_bindings
                    if b.target_property_id
                }
                # Prefer human-readable label from 姓名 / name-like data props
                label_cols = [
                    b.source_column
                    for b in prop_bindings
                    if b.target_property_id
                    and props.get(b.target_property_id)
                    and props[b.target_property_id].kind == "data"
                    and props[b.target_property_id].label
                    in {"姓名", "名称", "客户名称", "name", "full_name"}
                ]

                rows, fetch_err = await self._fetch_source_rows(
                    ds, table.table_schema, table.table_name, batch=500
                )
                if fetch_err:
                    fetch_errors.append(
                        f"{table.table_schema}.{table.table_name}: {fetch_err}"
                    )
                    continue
                if not rows:
                    logger.info(
                        "structured extract: no rows in %s.%s",
                        table.table_schema,
                        table.table_name,
                    )
                    continue

                total_rows = len(rows)
                for ri, row in enumerate(rows):
                    raw_uri = row.get(uri_col)
                    if raw_uri is None or str(raw_uri).strip() == "":
                        skipped += 1
                        continue
                    local = str(raw_uri).strip()
                    display = local
                    for lc in label_cols:
                        v = row.get(lc)
                        if v is not None and str(v).strip():
                            display = str(v).strip()
                            break

                    existing = await self.instance_repo.find_by_local_name(
                        session, task.schema_id, mapping.class_id, local
                    )
                    if not existing:
                        existing = await self.instance_repo.find_by_label(
                            session, task.schema_id, mapping.class_id, local
                        )

                    if existing:
                        existing.label = display
                        existing.local_name = local
                        existing.source_type = "structured_mapping"
                        existing.source_ref = {
                            "mapping_id": str(mapping.id),
                            "uri_column": uri_col,
                            "uri": local,
                            "row": ri,
                        }
                        existing.extraction_task_id = task_id
                        existing.confidence = Decimal("100")
                        existing.schema_version = schema_version
                        inst = existing
                        updated += 1
                    else:
                        inst = OntologyInstance(
                            schema_id=task.schema_id,
                            class_id=mapping.class_id,
                            label=display,
                            local_name=local,
                            source_type="structured_mapping",
                            source_ref={
                                "mapping_id": str(mapping.id),
                                "uri_column": uri_col,
                                "uri": local,
                                "row": ri,
                            },
                            extraction_task_id=task_id,
                            confidence=Decimal("100"),
                            schema_version=schema_version,
                        )
                        inst = await self.instance_repo.create(session, inst)
                        created += 1

                    values: list[InstanceDataValue] = []
                    mapped_data_prop_ids: list[uuid.UUID] = [
                        p.id
                        for b in prop_bindings
                        if b.target_property_id
                        and (p := props.get(b.target_property_id)) is not None
                        and p.kind == "data"
                    ]
                    for b in prop_bindings:
                        if not b.target_property_id:
                            continue
                        prop = props.get(b.target_property_id)
                        if not prop:
                            continue
                        val = row.get(b.source_column)
                        if val is None:
                            continue
                        if prop.kind == "data":
                            values.append(
                                InstanceDataValue(
                                    instance_id=inst.id,
                                    property_id=prop.id,
                                    value=str(val),
                                )
                            )
                        else:
                            if not prop.range_class_id:
                                continue
                            target = await self.instance_repo.find_by_label(
                                session, task.schema_id, prop.range_class_id, str(val)
                            )
                            if not target:
                                target = await self.instance_repo.create(
                                    session,
                                    OntologyInstance(
                                        schema_id=task.schema_id,
                                        class_id=prop.range_class_id,
                                        label=str(val),
                                        local_name=label_to_local_name(str(val)),
                                        source_type="structured_mapping",
                                        extraction_task_id=task_id,
                                        schema_version=schema_version,
                                    ),
                                )
                            # Avoid duplicate object edges on re-run
                            existing_rel = await session.execute(
                                select(InstanceRelation).where(
                                    InstanceRelation.subject_instance_id == inst.id,
                                    InstanceRelation.property_id == prop.id,
                                    InstanceRelation.object_instance_id == target.id,
                                )
                            )
                            if existing_rel.scalar_one_or_none() is None:
                                await self.relation_repo.create(
                                    session,
                                    InstanceRelation(
                                        subject_instance_id=inst.id,
                                        property_id=prop.id,
                                        object_instance_id=target.id,
                                    ),
                                )
                    if mapped_data_prop_ids:
                        await self.instance_repo.replace_data_values(
                            session,
                            inst.id,
                            values,
                            property_ids=mapped_data_prop_ids,
                        )
                    prog = ((mi + (ri + 1) / total_rows) / max(len(mapping_ids), 1)) * 100
                    if ri % 20 == 0:
                        await runner.update_task_progress(task_id, progress=min(prog, 99))
                        await session.commit()

            if fetch_errors and created == 0 and updated == 0:
                raise RuntimeError(
                    "结构化抽取读取源表失败: " + "; ".join(fetch_errors)
                )

            await session.commit()
            await self.schema_repo.invalidate_graph_cache(session, task.schema_id)
            await session.commit()
            await runner.update_task_progress(
                task_id,
                status="succeeded",
                progress=100,
                output_summary={
                    "instances_created": created,
                    "instances_updated": updated,
                    "rows_skipped": skipped,
                    "schema_version": schema_version,
                    "fetch_errors": fetch_errors or None,
                },
            )

    async def _run_business_logic(self, task_id: uuid.UUID) -> None:
        from app.services.topology_index_service import TopologyIndexService
        from app.services.topology_service import TopologyService
        from app.topology.logic_graph import LogicGraph
        from app.topology.pipeline import (
            build_from_logic,
            catalog_for_prompt,
            extract_logic_graphs,
        )

        async with session_scope() as session:
            task = await self.task_repo.get_by_id(session, task_id)
            assert task and task.schema_id
            payload = task.input or {}
            schema_id = task.schema_id
            schema_version = payload.get("schema_version")
            file_ids = [parse_uuid(x) for x in payload.get("file_ids", [])]
            files = await self.file_repo.list_by_ids(session, file_ids)
            texts = [await self._load_file_text(session, f) for f in files]
            file_id_strs = [str(f.id) for f in files]
            index = await TopologyIndexService().build_index(
                session, str(schema_id), schema_version=schema_version
            )
            if not index.instances:
                raise RuntimeError("本体模型下没有实例，无法组合业务逻辑拓扑")
            catalog = catalog_for_prompt(index, per_class_limit=40)
            llm = await self._llm_for_task(session, task)
            graph_name = payload.get("name") or ""
            ontology_model_id = payload.get("ontology_model_id")

        await runner.update_task_progress(task_id, progress=30)

        async def extract(chunk: str, cat: dict) -> LogicGraph:
            ai = await llm.extract_business_logic_topology(chunk, cat)
            if not ai.success or not ai.result:
                raise RuntimeError(ai.error or "业务逻辑拓扑抽取失败")
            return ai.result

        async def on_progress(pct: float) -> None:
            await runner.update_task_progress(task_id, progress=pct)

        logic = await extract_logic_graphs(
            extract,
            texts,
            catalog,
            on_progress=on_progress,
            max_chunks=8,
        )
        await runner.update_task_progress(task_id, progress=75)
        graph, warnings, stats = build_from_logic(logic, index, name=graph_name)
        await runner.update_task_progress(task_id, progress=90)

        async with session_scope() as session:
            obj = await TopologyService().persist_extracted(
                session,
                schema_id=schema_id,
                schema_version=index.schema_version,
                task_id=task_id,
                file_ids=file_id_strs,
                graph=graph,
                warnings=warnings,
                stats=stats,
                type_mapping={
                    cls.label: [cls.id]
                    for cls in index.classes.values()
                },
                name=graph.name,
                description=graph.description,
                ontology_model_id=ontology_model_id,
            )
            await session.commit()

        await runner.update_task_progress(
            task_id,
            status="succeeded",
            progress=100,
            output_summary={
                "topology_id": str(obj.id),
                "node_count": obj.node_count,
                "edge_count": obj.edge_count,
                "grounded_ratio": (
                    float(obj.grounded_ratio) if obj.grounded_ratio is not None else None
                ),
                "warning_count": len(warnings),
            },
        )

    async def _schema_snapshot(self, session: AsyncSession, schema_id: uuid.UUID) -> SchemaSnapshot:
        classes = await self.class_repo.list_by_schema(session, schema_id)
        props = await self.prop_repo.list_by_schema(session, schema_id)
        range_labels = {c.id: c.label for c in classes}
        by_class: dict[uuid.UUID, list[SchemaSnapshotProperty]] = {c.id: [] for c in classes}
        for p in props:
            by_class.setdefault(p.domain_class_id, []).append(
                SchemaSnapshotProperty(
                    label=p.label,
                    kind=p.kind,  # type: ignore[arg-type]
                    datatype=p.datatype,
                    range_class_label=range_labels.get(p.range_class_id) if p.range_class_id else None,
                    local_name=p.local_name,
                )
            )
        return SchemaSnapshot(
            classes=[
                SchemaSnapshotClass(
                    label=c.label,
                    local_name=c.local_name,
                    properties=by_class.get(c.id, []),
                )
                for c in classes
            ]
        )

    async def _persist_extracted(
        self,
        session: AsyncSession,
        *,
        schema_id: uuid.UUID,
        task_id: uuid.UUID,
        extracted: list,
        source_type: str,
        source_ref: dict,
        schema_version: int | None = None,
    ) -> None:
        classes_list = await self.class_repo.list_by_schema(session, schema_id)
        classes: dict[str, OntologyClass] = {}
        for c in classes_list:
            classes[c.label] = c
            if c.local_name:
                classes[c.local_name] = c
        props_by_class: dict[uuid.UUID, dict[str, OntologyProperty]] = {}
        for p in await self.prop_repo.list_by_schema(session, schema_id):
            bucket = props_by_class.setdefault(p.domain_class_id, {})
            bucket[p.label] = p
            if p.local_name:
                bucket[p.local_name] = p

        created: dict[str, OntologyInstance] = {}
        for item in extracted:
            cls = classes.get(item.class_label)
            if not cls:
                continue
            local = item.local_name or label_to_local_name(item.label)
            # Upsert by (class, label) — same as extract mint_iri identity
            existing = await self.instance_repo.find_by_label(
                session, schema_id, cls.id, item.label
            )
            if existing:
                existing.extraction_task_id = task_id
                existing.source_type = source_type
                existing.source_ref = item.source_ref or source_ref
                existing.local_name = existing.local_name or local
                if schema_version is not None:
                    existing.schema_version = schema_version
                if item.confidence is not None:
                    existing.confidence = Decimal(str(item.confidence))
                await session.flush()
                created[item.label] = existing
            else:
                inst = OntologyInstance(
                    schema_id=schema_id,
                    class_id=cls.id,
                    label=item.label,
                    local_name=local,
                    source_type=source_type,
                    source_ref=item.source_ref or source_ref,
                    confidence=Decimal(str(item.confidence or 80)),
                    schema_version=schema_version,
                    extraction_task_id=task_id,
                )
                inst = await self.instance_repo.create(session, inst)
                created[item.label] = inst
            values = []
            prop_map = props_by_class.get(cls.id, {})
            inst_obj = created[item.label]
            for dv in item.data_values:
                prop = prop_map.get(dv.property_label)
                if prop and prop.kind == "data":
                    values.append(
                        InstanceDataValue(
                            instance_id=inst_obj.id, property_id=prop.id, value=dv.value
                        )
                    )
            if values:
                await self.instance_repo.add_data_values(session, values)

        for item in extracted:
            inst = created.get(item.label)
            if not inst:
                continue
            cls = classes.get(item.class_label)
            if not cls:
                continue
            prop_map = props_by_class.get(cls.id, {})
            for rel in item.relations:
                prop = prop_map.get(rel.property_label)
                target = created.get(rel.target_instance_label)
                if prop and target and prop.kind == "object":
                    await self.relation_repo.create(
                        session,
                        InstanceRelation(
                            subject_instance_id=inst.id,
                            property_id=prop.id,
                            object_instance_id=target.id,
                        ),
                    )

    async def _fetch_source_rows(
        self, ds, table_schema: str, table_name: str, *, batch: int = 500
    ) -> tuple[list[dict], str | None]:
        """Batch SELECT from source DB.

        Returns (rows, error). error is set when the source is unreachable / query fails;
        empty rows with error=None means the table genuinely has no data.
        """
        if ds.db_type not in ("postgres", "gaussdb"):
            msg = f"structured ETL only fully supports postgres/gaussdb (got {ds.db_type})"
            logger.warning(msg)
            return [], msg
        try:
            import asyncpg

            pwd = decrypt_password(ds.password_enc)
            conn = await asyncpg.connect(
                host=ds.host,
                port=ds.port,
                user=ds.username,
                password=pwd,
                database=ds.database_name,
                timeout=10,
            )
            try:
                rows: list[dict] = []
                offset = 0
                # Quote identifiers; schema/table come from reflection metadata, not user free text.
                q = (
                    f'SELECT * FROM "{table_schema}"."{table_name}" '
                    f"LIMIT {int(batch)} OFFSET "
                )
                while True:
                    chunk = await conn.fetch(q + str(offset))
                    if not chunk:
                        break
                    for r in chunk:
                        rows.append(dict(r))
                    if len(chunk) < batch:
                        break
                    offset += batch
                return rows, None
            finally:
                await conn.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("source fetch failed: %s", exc)
            return [], str(exc)

    async def _instance_summary(self, session: AsyncSession, obj: OntologyInstance) -> InstanceRead:
        cls = await self.class_repo.get_by_id(session, obj.class_id)
        return InstanceRead(
            id=str(obj.id),
            schema_id=str(obj.schema_id),
            class_id=str(obj.class_id),
            class_label=cls.label if cls else None,
            label=obj.label,
            local_name=obj.local_name,
            source_type=obj.source_type,
            source_ref=obj.source_ref,
            confidence=float(obj.confidence) if obj.confidence is not None else None,
            schema_version=obj.schema_version,
            extraction_task_id=uid(obj.extraction_task_id),
            created_at=obj.created_at,
        )

    async def _instance_detail(self, session: AsyncSession, obj: OntologyInstance) -> InstanceRead:
        base = await self._instance_summary(session, obj)
        from app.schemas.extraction import InstanceDataValueRead, InstanceRelationRead

        data_values = []
        for dv in obj.data_values or []:
            prop = await self.prop_repo.get_by_id(session, dv.property_id)
            data_values.append(
                InstanceDataValueRead(
                    property_id=str(dv.property_id),
                    property_label=prop.label if prop else None,
                    value=dv.value,
                )
            )
        relations = []
        for rel in obj.subject_relations or []:
            prop = await self.prop_repo.get_by_id(session, rel.property_id)
            target = await self.instance_repo.get_by_id(session, rel.object_instance_id)
            relations.append(
                InstanceRelationRead(
                    property_id=str(rel.property_id),
                    property_label=prop.label if prop else None,
                    object_instance_id=str(rel.object_instance_id),
                    object_instance_label=target.label if target else None,
                )
            )
        base.data_values = data_values
        base.relations = relations
        return base
