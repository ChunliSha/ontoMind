"""Private runners and persistence helpers mixed into ExtractionService."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

import asyncpg
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import resolve_llm_provider
from app.ai.base import ExtractedInstance, SchemaSnapshot, SchemaSnapshotClass, SchemaSnapshotProperty
from app.core.exceptions import AppError, ErrorCode
from app.core.security import decrypt_password
from app.db.session import session_scope
from app.models.extraction import ExtractionTask
from app.models.instance import InstanceDataValue, InstanceRelation, OntologyInstance
from app.models.schema import OntologyClass, OntologyProperty
from app.rdf.ttl_builder import label_to_local_name
from app.schemas.extraction import InstanceDataValueRead, InstanceRead, InstanceRelationRead
from app.services._utils import parse_uuid, uid
from app.services.extraction_helpers import (
    display_label_from_row,
    index_classes_by_name,
    index_props_by_class,
    label_source_columns,
    mapped_data_property_ids,
    merge_extracted_instance,
)
from app.services.file_service import is_placeholder_polluted
from app.services.ontology_model_service import OntologyModelService
from app.services.topology_index_service import TopologyIndexService
from app.services.topology_service import TopologyService
from app.storage import get_storage
from app.tasks import runner
from app.topology.logic_graph import LogicGraph
from app.topology.pipeline import build_from_logic, catalog_for_prompt, extract_logic_graphs

logger = logging.getLogger(__name__)


@dataclass
class StructuredCounts:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    fetch_errors: list[str] = field(default_factory=list)


class ExtractionTaskMixin:
    @staticmethod
    def _mark_orphan_failed(task: ExtractionTask) -> None:
        task.status = "failed"
        task.error_message = "任务进程已丢失，已自动中断"
        task.finished_at = datetime.now(timezone.utc)

    @staticmethod
    def _assert_induce_ok(result) -> None:
        if not result.success or not result.result:
            raise RuntimeError(result.error or "schema induction failed")
        if not result.result.classes:
            raise RuntimeError("模型未返回任何类，请检查文档内容或更换模型后重试")

    @staticmethod
    def _induced_range_id(induced, label_to_class: dict[str, OntologyClass]):
        is_object = induced.kind == "object" and induced.range_class_label
        if not is_object:
            return None
        range_cls = label_to_class.get(induced.range_class_label)
        return range_cls.id if range_cls else None

    async def _adopt_or_clear_running(
        self,
        session: AsyncSession,
        *,
        task_type: str,
        schema_id: uuid.UUID | None,
    ) -> uuid.UUID | None:
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
        runner.request_cancel(task_id)
        row = await self.task_repo.get_by_id(session, task_id)
        still_active = bool(row and row.status in ("pending", "running"))
        if not still_active:
            return
        row.status = "failed"
        row.error_message = runner.CANCEL_MESSAGE
        row.finished_at = datetime.now(timezone.utc)
        await session.flush()

    async def _llm_for_task(self, session: AsyncSession, task: ExtractionTask):
        model_id = (task.input or {}).get("model_id")
        return await resolve_llm_provider(session, model_id)

    async def _load_file_text(self, session: AsyncSession, file_obj) -> str:
        if not file_obj.ontology_md_path:
            return await self.file_svc.ensure_clean_extracted_text(session, file_obj)
        try:
            raw = await get_storage(file_obj.storage_backend).read(file_obj.ontology_md_path)
            markdown = raw.decode("utf-8", errors="ignore")
        except Exception as exc:  # noqa: BLE001
            logger.warning("ontology_md read failed for %s: %s", file_obj.id, exc)
            return await self.file_svc.ensure_clean_extracted_text(session, file_obj)
        usable = bool(markdown.strip()) and not is_placeholder_polluted(markdown)
        if usable:
            return markdown
        return await self.file_svc.ensure_clean_extracted_text(session, file_obj)

    async def _require_mapping(self, session: AsyncSession, mapping_id: str, schema_id: uuid.UUID):
        mapping = await self.mapping_repo.get_by_id(session, parse_uuid(mapping_id))
        if not mapping:
            raise AppError(
                ErrorCode.NOT_FOUND,
                message="所选字段映射不存在或已失效（可能因重新同步表结构被删除），请重新配置并勾选映射",
            )
        if not mapping.bindings:
            raise AppError(
                ErrorCode.MAPPING_001,
                message="所选映射没有字段绑定，请重新配置字段映射",
            )
        has_uri = any(binding.target_kind == "instance_uri" for binding in mapping.bindings)
        if not has_uri:
            raise AppError(ErrorCode.MAPPING_001)
        if mapping.schema_id != schema_id:
            raise AppError(
                ErrorCode.MAPPING_001,
                message="所选映射不属于当前 Schema，请重新勾选",
            )
        return mapping

    async def _resolve_logic_schema(
        self, session: AsyncSession, body
    ) -> tuple[uuid.UUID, int | None, uuid.UUID | None]:
        if body.ontology_model_id:
            model = await OntologyModelService().get_orm(session, body.ontology_model_id)
            return model.schema_id, model.schema_version, model.id
        schema_id = parse_uuid(body.schema_id or "")
        return schema_id, body.schema_version, None

    async def _run_schema_induction(self, task_id: uuid.UUID) -> None:
        async with session_scope() as session:
            task = await self.task_repo.get_by_id(session, task_id)
            assert task and task.schema_id
            file_ids = [parse_uuid(item) for item in (task.input or {}).get("file_ids", [])]
            files = await self.file_repo.list_by_ids(session, file_ids)
            texts = [await self._load_file_text(session, file_obj) for file_obj in files]
            existing = [
                cls.label for cls in await self.class_repo.list_by_schema(session, task.schema_id)
            ]
            llm = await self._llm_for_task(session, task)
            if not any((text or "").strip() for text in texts):
                raise RuntimeError("所选文档无可抽取文本，请确认文件已解析完成后再抽取")
            result = await llm.induce_schema(texts, existing)
            self._assert_induce_ok(result)
            created_c, created_p = await self._apply_induce_result(session, task, result, task_id)
            await self._mark_schema_ai_induced(session, task.schema_id)
            await session.commit()
            await runner.update_task_progress(
                task_id,
                status="succeeded",
                progress=100,
                output_summary={"classes_created": created_c, "properties_created": created_p},
            )

    async def _mark_schema_ai_induced(self, session: AsyncSession, schema_id: uuid.UUID) -> None:
        schema = await self.schema_repo.get_by_id(session, schema_id)
        if schema and schema.source == "manual":
            schema.source = "ai_induced"
            schema.updated_at = datetime.now(timezone.utc)
        await self.schema_repo.invalidate_graph_cache(session, schema_id)

    async def _apply_induce_result(
        self, session: AsyncSession, task: ExtractionTask, result, task_id: uuid.UUID
    ) -> tuple[int, int]:
        label_to_class = {
            cls.label: cls for cls in await self.class_repo.list_by_schema(session, task.schema_id)
        }
        total_steps = max(len(result.result.classes) + len(result.result.properties), 1)
        created_c, step = await self._create_induced_classes(
            session, task, result.result.classes, label_to_class, task_id, total_steps
        )
        created_p = await self._create_induced_properties(
            session, task, result.result.properties, label_to_class, task_id, total_steps, step
        )
        return created_c, created_p

    async def _create_induced_classes(
        self,
        session: AsyncSession,
        task: ExtractionTask,
        induced_classes,
        label_to_class: dict[str, OntologyClass],
        task_id: uuid.UUID,
        total_steps: int,
    ) -> tuple[int, int]:
        created = 0
        step = 0
        for induced in induced_classes:
            if induced.label in label_to_class:
                continue
            obj = OntologyClass(
                schema_id=task.schema_id,
                label=induced.label,
                local_name=induced.local_name or label_to_local_name(induced.label),
                description=induced.description,
                source="ai",
            )
            obj = await self.class_repo.create(session, obj)
            label_to_class[induced.label] = obj
            created += 1
            step += 1
            await runner.update_task_progress(task_id, progress=step / total_steps * 100)
        return created, step

    async def _create_induced_properties(
        self,
        session: AsyncSession,
        task: ExtractionTask,
        induced_props,
        label_to_class: dict[str, OntologyClass],
        task_id: uuid.UUID,
        total_steps: int,
        step: int,
    ) -> int:
        created = 0
        for induced in induced_props:
            cls = label_to_class.get(induced.class_label)
            if not cls:
                continue
            if await self.prop_repo.get_by_label(session, cls.id, induced.label):
                continue
            range_id = self._induced_range_id(induced, label_to_class)
            prop = OntologyProperty(
                schema_id=task.schema_id,
                domain_class_id=cls.id,
                label=induced.label,
                local_name=label_to_local_name(induced.label),
                kind=induced.kind,
                datatype=induced.datatype,
                range_class_id=range_id,
                required=induced.required,
                multi=induced.multi,
                source="ai",
                confidence=Decimal(str(induced.confidence or 80)),
            )
            await self.prop_repo.create(session, prop)
            created += 1
            step += 1
            await runner.update_task_progress(
                task_id, progress=min(step / total_steps * 100, 99)
            )
        return created

    async def _run_unstructured(self, task_id: uuid.UUID) -> None:
        async with session_scope() as session:
            task = await self.task_repo.get_by_id(session, task_id)
            assert task and task.schema_id
            schema = await self.schema_repo.get_by_id(session, task.schema_id)
            assert schema
            schema_version = int(
                (task.input or {}).get("schema_version") or schema.version or 1
            )
            await self._maybe_replace_unstructured(session, task, schema_version)
            snapshot = await self._schema_snapshot(session, task.schema_id)
            file_ids = [parse_uuid(item) for item in (task.input or {}).get("file_ids", [])]
            files = await self.file_repo.list_by_ids(session, file_ids)
            llm = await self._llm_for_task(session, task)
            await runner.update_task_progress(
                task_id,
                progress=3,
                output_summary={"stage": "准备文档与本体，即将调用模型…"},
            )
            merged, ok_count, fail_count, file_names = await self._extract_unstructured_files(
                session, task_id, files, llm, snapshot
            )
            if runner.is_cancelled(task_id):
                raise runner.ExtractionCancelled(runner.CANCEL_MESSAGE)
            await self._persist_unstructured_merged(
                session, task, schema_version, task_id, merged, file_names
            )
            await runner.update_task_progress(
                task_id,
                status="succeeded",
                progress=100,
                output_summary={
                    "succeeded": ok_count,
                    "failed": fail_count,
                    "schema_version": schema_version,
                    "instances": len(merged),
                },
            )

    async def _maybe_replace_unstructured(
        self, session: AsyncSession, task: ExtractionTask, schema_version: int
    ) -> None:
        if not (task.input or {}).get("replace_existing", True):
            return
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

    async def _extract_unstructured_files(
        self, session, task_id, files, llm, snapshot
    ) -> tuple[dict[tuple[str, str], ExtractedInstance], int, int, list[str]]:
        merged: dict[tuple[str, str], ExtractedInstance] = {}
        file_names: list[str] = []
        ok_count, fail_count = 0, 0
        total = max(len(files), 1)
        for index, file_obj in enumerate(files):
            if runner.is_cancelled(task_id):
                raise runner.ExtractionCancelled(runner.CANCEL_MESSAGE)
            extracted = await self._extract_one_unstructured_file(
                session, task_id, file_obj, llm, snapshot, index, total, len(files)
            )
            if extracted is None:
                fail_count += 1
                continue
            for inst in extracted:
                merge_extracted_instance(merged, inst)
            ok_count += 1
            file_names.append(file_obj.name)
        return merged, ok_count, fail_count, file_names

    async def _extract_one_unstructured_file(
        self, session, task_id, file_obj, llm, snapshot, index, total, file_count
    ) -> list[ExtractedInstance] | None:
        try:
            text_content = await self._load_file_text(session, file_obj)
            if not text_content.strip():
                await runner.update_task_progress(task_id, progress=(index + 1) / total * 100)
                return None
            await runner.update_task_progress(
                task_id,
                progress=min(90, 8 + index / total * 80),
                output_summary={
                    "stage": (
                        f"正在抽取「{file_obj.name}」（{index + 1}/{file_count}）："
                        "实体识别 → 关系抽取 → 三元组，模型调用可能需要数分钟"
                    ),
                },
            )
            ai = await llm.extract_instances([text_content], snapshot, task_id=task_id)
            if runner.is_cancelled(task_id):
                raise runner.ExtractionCancelled(runner.CANCEL_MESSAGE)
            if not ai.success or not ai.result:
                logger.warning("unstructured extract failed for %s: %s", file_obj.id, ai.error)
                await runner.update_task_progress(task_id, progress=(index + 1) / total * 100)
                return None
            await runner.update_task_progress(task_id, progress=(index + 1) / total * 100)
            return list(ai.result.instances)
        except runner.ExtractionCancelled:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("file %s extraction failed", file_obj.id)
            await runner.update_task_progress(task_id, progress=(index + 1) / total * 100)
            return None

    async def _persist_unstructured_merged(
        self, session, task, schema_version, task_id, merged, file_names
    ) -> None:
        if merged:
            await self._persist_extracted(
                session,
                schema_id=task.schema_id,
                schema_version=schema_version,
                task_id=task_id,
                extracted=list(merged.values()),
                source_type="ai_unstructured",
                source_ref={"file_names": file_names, "file_count": len(file_names), "deduped": True},
            )
        await session.commit()
        await self.schema_repo.invalidate_graph_cache(session, task.schema_id)
        await session.commit()

    async def _run_structured(self, task_id: uuid.UUID) -> None:
        async with session_scope() as session:
            task = await self.task_repo.get_by_id(session, task_id)
            assert task and task.schema_id
            schema = await self.schema_repo.get_by_id(session, task.schema_id)
            if not schema:
                raise RuntimeError("schema not found for structured extraction")
            schema_version = int(schema.version or 1)
            mapping_ids = [parse_uuid(item) for item in (task.input or {}).get("mapping_ids", [])]
            counts = StructuredCounts()
            for map_index, mapping_id in enumerate(mapping_ids):
                await self._process_one_mapping(
                    session, task, task_id, mapping_id, map_index, mapping_ids, schema_version, counts
                )
            no_rows = counts.created == 0 and counts.updated == 0
            if counts.fetch_errors and no_rows:
                raise RuntimeError("结构化抽取读取源表失败: " + "; ".join(counts.fetch_errors))
            await session.commit()
            await self.schema_repo.invalidate_graph_cache(session, task.schema_id)
            await session.commit()
            await runner.update_task_progress(
                task_id,
                status="succeeded",
                progress=100,
                output_summary={
                    "instances_created": counts.created,
                    "instances_updated": counts.updated,
                    "rows_skipped": counts.skipped,
                    "schema_version": schema_version,
                    "fetch_errors": counts.fetch_errors or None,
                },
            )

    async def _process_one_mapping(
        self,
        session,
        task,
        task_id,
        mapping_id,
        map_index,
        mapping_ids,
        schema_version,
        counts: StructuredCounts,
    ) -> None:
        mapping = await self.mapping_repo.get_by_id(session, mapping_id)
        table = await self.table_repo.get_by_id(session, mapping.table_id) if mapping else None
        data_source = await self.db_repo.get_by_id(session, table.data_source_id) if table else None
        if not mapping or not table or not data_source:
            return
        uri_col = next(
            (binding.source_column for binding in mapping.bindings if binding.target_kind == "instance_uri"),
            None,
        )
        if not uri_col:
            raise AppError(ErrorCode.MAPPING_001)
        prop_bindings = [binding for binding in mapping.bindings if binding.target_kind == "property"]
        props = {
            binding.target_property_id: await self.prop_repo.get_by_id(session, binding.target_property_id)
            for binding in prop_bindings
            if binding.target_property_id
        }
        label_cols = label_source_columns(prop_bindings, props)
        rows, fetch_err = await self._fetch_source_rows(
            data_source, table.table_schema, table.table_name, batch=500
        )
        if fetch_err:
            counts.fetch_errors.append(f"{table.table_schema}.{table.table_name}: {fetch_err}")
            return
        if not rows:
            logger.info("structured extract: no rows in %s.%s", table.table_schema, table.table_name)
            return
        await self._process_mapping_rows(
            session, task, task_id, mapping, uri_col, prop_bindings, props, label_cols,
            rows, map_index, mapping_ids, schema_version, counts,
        )

    async def _process_mapping_rows(
        self,
        session,
        task,
        task_id,
        mapping,
        uri_col,
        prop_bindings,
        props,
        label_cols,
        rows,
        map_index,
        mapping_ids,
        schema_version,
        counts: StructuredCounts,
    ) -> None:
        total_rows = len(rows)
        for row_index, row in enumerate(rows):
            raw_uri = row.get(uri_col)
            if raw_uri is None or str(raw_uri).strip() == "":
                counts.skipped += 1
                continue
            local = str(raw_uri).strip()
            display = display_label_from_row(row, local, label_cols)
            inst, created = await self._upsert_structured_instance(
                session, task, task_id, mapping, local, display, uri_col, row_index, schema_version
            )
            if created:
                counts.created += 1
            else:
                counts.updated += 1
            await self._apply_row_properties(
                session, task, task_id, inst, row, prop_bindings, props, schema_version
            )
            progress = ((map_index + (row_index + 1) / total_rows) / max(len(mapping_ids), 1)) * 100
            if row_index % 20 == 0:
                await runner.update_task_progress(task_id, progress=min(progress, 99))
                await session.commit()

    async def _upsert_structured_instance(
        self,
        session,
        task,
        task_id,
        mapping,
        local: str,
        display: str,
        uri_col: str,
        row_index: int,
        schema_version: int,
    ) -> tuple[OntologyInstance, bool]:
        source_ref = {
            "mapping_id": str(mapping.id),
            "uri_column": uri_col,
            "uri": local,
            "row": row_index,
        }
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
            existing.source_ref = source_ref
            existing.extraction_task_id = task_id
            existing.confidence = Decimal("100")
            existing.schema_version = schema_version
            return existing, False
        inst = OntologyInstance(
            schema_id=task.schema_id,
            class_id=mapping.class_id,
            label=display,
            local_name=local,
            source_type="structured_mapping",
            source_ref=source_ref,
            extraction_task_id=task_id,
            confidence=Decimal("100"),
            schema_version=schema_version,
        )
        inst = await self.instance_repo.create(session, inst)
        return inst, True

    async def _apply_row_properties(
        self, session, task, task_id, inst, row, prop_bindings, props, schema_version
    ) -> None:
        values: list[InstanceDataValue] = []
        mapped_ids = mapped_data_property_ids(prop_bindings, props)
        for binding in prop_bindings:
            data_value = await self._apply_one_binding(
                session, task, task_id, inst, row, binding, props, schema_version
            )
            if data_value is not None:
                values.append(data_value)
        if mapped_ids:
            await self.instance_repo.replace_data_values(
                session, inst.id, values, property_ids=mapped_ids
            )

    async def _apply_one_binding(
        self, session, task, task_id, inst, row, binding, props, schema_version
    ) -> InstanceDataValue | None:
        if not binding.target_property_id:
            return None
        prop = props.get(binding.target_property_id)
        if not prop:
            return None
        val = row.get(binding.source_column)
        if val is None:
            return None
        if prop.kind == "data":
            return InstanceDataValue(instance_id=inst.id, property_id=prop.id, value=str(val))
        await self._ensure_object_relation(session, task, task_id, inst, prop, str(val), schema_version)
        return None

    async def _ensure_object_relation(
        self, session, task, task_id, inst, prop, value: str, schema_version: int
    ) -> None:
        if not prop.range_class_id:
            return
        target = await self.instance_repo.find_by_label(
            session, task.schema_id, prop.range_class_id, value
        )
        if not target:
            target = await self.instance_repo.create(
                session,
                OntologyInstance(
                    schema_id=task.schema_id,
                    class_id=prop.range_class_id,
                    label=value,
                    local_name=label_to_local_name(value),
                    source_type="structured_mapping",
                    extraction_task_id=task_id,
                    schema_version=schema_version,
                ),
            )
        existing_rel = await session.execute(
            select(InstanceRelation).where(
                InstanceRelation.subject_instance_id == inst.id,
                InstanceRelation.property_id == prop.id,
                InstanceRelation.object_instance_id == target.id,
            )
        )
        if existing_rel.scalar_one_or_none() is not None:
            return
        await self.relation_repo.create(
            session,
            InstanceRelation(
                subject_instance_id=inst.id,
                property_id=prop.id,
                object_instance_id=target.id,
            ),
        )

    async def _run_business_logic(self, task_id: uuid.UUID) -> None:
        async with session_scope() as session:
            prepared = await self._prepare_business_logic(session, task_id)
        await runner.update_task_progress(task_id, progress=30)
        logic = await extract_logic_graphs(
            self._bound_logic_extract(prepared["llm"]),
            prepared["texts"],
            prepared["catalog"],
            on_progress=self._bound_logic_progress(task_id),
            max_chunks=8,
        )
        await runner.update_task_progress(task_id, progress=75)
        graph, warnings, stats = build_from_logic(
            logic, prepared["index"], name=prepared["graph_name"]
        )
        await runner.update_task_progress(task_id, progress=90)
        await self._persist_business_logic(task_id, prepared, graph, warnings, stats)

    async def _prepare_business_logic(self, session: AsyncSession, task_id: uuid.UUID) -> dict:
        task = await self.task_repo.get_by_id(session, task_id)
        assert task and task.schema_id
        payload = task.input or {}
        file_ids = [parse_uuid(item) for item in payload.get("file_ids", [])]
        files = await self.file_repo.list_by_ids(session, file_ids)
        texts = [await self._load_file_text(session, file_obj) for file_obj in files]
        index = await TopologyIndexService().build_index(
            session, str(task.schema_id), schema_version=payload.get("schema_version")
        )
        if not index.instances:
            raise RuntimeError("本体模型下没有实例，无法组合业务逻辑拓扑")
        llm = await self._llm_for_task(session, task)
        return {
            "schema_id": task.schema_id,
            "texts": texts,
            "file_id_strs": [str(file_obj.id) for file_obj in files],
            "index": index,
            "catalog": catalog_for_prompt(index, per_class_limit=40),
            "llm": llm,
            "graph_name": payload.get("name") or "",
            "ontology_model_id": payload.get("ontology_model_id"),
        }

    def _bound_logic_extract(self, llm):
        async def extract(chunk: str, catalog: dict) -> LogicGraph:
            return await self._llm_extract_logic(llm, chunk, catalog)

        return extract

    def _bound_logic_progress(self, task_id: uuid.UUID):
        async def on_progress(pct: float) -> None:
            await runner.update_task_progress(task_id, progress=pct)

        return on_progress

    async def _llm_extract_logic(self, llm, chunk: str, catalog: dict) -> LogicGraph:
        ai = await llm.extract_business_logic_topology(chunk, catalog)
        if not ai.success or not ai.result:
            raise RuntimeError(ai.error or "业务逻辑拓扑抽取失败")
        return ai.result

    async def _persist_business_logic(self, task_id, prepared, graph, warnings, stats) -> None:
        async with session_scope() as session:
            obj = await TopologyService().persist_extracted(
                session,
                schema_id=prepared["schema_id"],
                schema_version=prepared["index"].schema_version,
                task_id=task_id,
                file_ids=prepared["file_id_strs"],
                graph=graph,
                warnings=warnings,
                stats=stats,
                type_mapping={cls.label: [cls.id] for cls in prepared["index"].classes.values()},
                name=graph.name,
                description=graph.description,
                ontology_model_id=prepared["ontology_model_id"],
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
        range_labels = {cls.id: cls.label for cls in classes}
        by_class: dict[uuid.UUID, list[SchemaSnapshotProperty]] = {cls.id: [] for cls in classes}
        for prop in props:
            by_class.setdefault(prop.domain_class_id, []).append(
                SchemaSnapshotProperty(
                    label=prop.label,
                    kind=prop.kind,
                    datatype=prop.datatype,
                    range_class_label=range_labels.get(prop.range_class_id) if prop.range_class_id else None,
                    local_name=prop.local_name,
                )
            )
        return SchemaSnapshot(
            classes=[
                SchemaSnapshotClass(
                    label=cls.label,
                    local_name=cls.local_name,
                    properties=by_class.get(cls.id, []),
                )
                for cls in classes
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
        classes = index_classes_by_name(await self.class_repo.list_by_schema(session, schema_id))
        props_by_class = index_props_by_class(await self.prop_repo.list_by_schema(session, schema_id))
        created: dict[str, OntologyInstance] = {}
        for item in extracted:
            await self._upsert_extracted_item(
                session, schema_id, task_id, item, classes, props_by_class,
                created, source_type, source_ref, schema_version,
            )
        await self._persist_extracted_relations(session, extracted, classes, props_by_class, created)

    async def _upsert_extracted_item(
        self,
        session,
        schema_id,
        task_id,
        item,
        classes,
        props_by_class,
        created,
        source_type,
        source_ref,
        schema_version,
    ) -> None:
        cls = classes.get(item.class_label)
        if not cls:
            return
        local = item.local_name or label_to_local_name(item.label)
        existing = await self.instance_repo.find_by_label(session, schema_id, cls.id, item.label)
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
            created[item.label] = await self.instance_repo.create(session, inst)
        await self._persist_item_data_values(session, item, cls, props_by_class, created)

    async def _persist_item_data_values(self, session, item, cls, props_by_class, created) -> None:
        values = []
        prop_map = props_by_class.get(cls.id, {})
        inst_obj = created[item.label]
        for data_val in item.data_values:
            prop = prop_map.get(data_val.property_label)
            if prop and prop.kind == "data":
                values.append(
                    InstanceDataValue(
                        instance_id=inst_obj.id, property_id=prop.id, value=data_val.value
                    )
                )
        if values:
            await self.instance_repo.add_data_values(session, values)

    async def _persist_extracted_relations(
        self, session, extracted, classes, props_by_class, created
    ) -> None:
        for item in extracted:
            inst = created.get(item.label)
            cls = classes.get(item.class_label)
            if not inst or not cls:
                continue
            prop_map = props_by_class.get(cls.id, {})
            for rel in item.relations:
                prop = prop_map.get(rel.property_label)
                target = created.get(rel.target_instance_label)
                can_link = prop and target and prop.kind == "object"
                if not can_link:
                    continue
                await self.relation_repo.create(
                    session,
                    InstanceRelation(
                        subject_instance_id=inst.id,
                        property_id=prop.id,
                        object_instance_id=target.id,
                    ),
                )

    async def _fetch_source_rows(
        self, data_source, table_schema: str, table_name: str, *, batch: int = 500
    ) -> tuple[list[dict], str | None]:
        if data_source.db_type not in ("postgres", "gaussdb"):
            msg = f"structured ETL only fully supports postgres/gaussdb (got {data_source.db_type})"
            logger.warning(msg)
            return [], msg
        try:
            conn = await self._connect_source(data_source)
        except Exception as exc:  # noqa: BLE001
            logger.warning("source fetch failed: %s", exc)
            return [], str(exc)
        try:
            rows = await self._fetch_all_rows(conn, table_schema, table_name, batch)
            return rows, None
        except Exception as exc:  # noqa: BLE001
            logger.warning("source fetch failed: %s", exc)
            return [], str(exc)
        finally:
            await conn.close()

    @staticmethod
    async def _connect_source(data_source):
        password = decrypt_password(data_source.password_enc)
        return await asyncpg.connect(
            host=data_source.host,
            port=data_source.port,
            user=data_source.username,
            password=password,
            database=data_source.database_name,
            timeout=10,
        )

    @staticmethod
    async def _fetch_all_rows(conn, table_schema: str, table_name: str, batch: int) -> list[dict]:
        rows: list[dict] = []
        offset = 0
        query = f'SELECT * FROM "{table_schema}"."{table_name}" LIMIT {int(batch)} OFFSET '
        while True:
            chunk = await conn.fetch(query + str(offset))
            if not chunk:
                break
            for record in chunk:
                rows.append(dict(record))
            if len(chunk) < batch:
                break
            offset += batch
        return rows

    async def _instance_summary(self, session: AsyncSession, obj: OntologyInstance) -> InstanceRead:
        cls = None
        if obj.class_id:
            cls = await self.class_repo.get_by_id(session, obj.class_id)
        return InstanceRead(
            id=str(obj.id),
            schema_id=str(obj.schema_id),
            class_id=str(obj.class_id) if obj.class_id else None,
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
        data_values = []
        for data_val in obj.data_values or []:
            prop = await self.prop_repo.get_by_id(session, data_val.property_id)
            data_values.append(
                InstanceDataValueRead(
                    property_id=str(data_val.property_id),
                    property_label=prop.label if prop else None,
                    value=data_val.value,
                )
            )
        relations = await self._collect_instance_relations(session, obj)
        base.data_values = data_values
        base.relations = relations
        return base

    async def _collect_instance_relations(
        self, session: AsyncSession, obj: OntologyInstance
    ) -> list[InstanceRelationRead]:
        relations: list[InstanceRelationRead] = []
        seen: set[tuple[str, str, str]] = set()
        for rel in obj.subject_relations or []:
            item = await self._relation_read(
                session, rel.property_id, rel.object_instance_id, "out", seen
            )
            if item is not None:
                relations.append(item)
        incoming = await self.relation_repo.list_by_object(session, obj.id)
        for rel in incoming:
            item = await self._relation_read(
                session, rel.property_id, rel.subject_instance_id, "in", seen
            )
            if item is not None:
                relations.append(item)
        return relations

    async def _relation_read(
        self, session, property_id, other_id, direction: str, seen: set[tuple[str, str, str]]
    ) -> InstanceRelationRead | None:
        key = (str(property_id), str(other_id), direction)
        if key in seen:
            return None
        seen.add(key)
        prop = await self.prop_repo.get_by_id(session, property_id)
        other = await self.instance_repo.get_by_id(session, other_id)
        other_cls = None
        if other and other.class_id:
            other_cls = await self.class_repo.get_by_id(session, other.class_id)
        label = other.label if other else None
        return InstanceRelationRead(
            property_id=str(property_id),
            property_label=prop.label if prop else None,
            object_instance_id=str(other_id),
            object_instance_label=label,
            object_label=label,
            object_class_label=other_cls.label if other_cls else None,
            direction=direction,
        )
