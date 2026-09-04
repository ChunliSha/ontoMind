"""Atomic instance correction: class, data values, outgoing relations, delete."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ErrorCode
from app.models.instance import InstanceDataValue, InstanceRelation, OntologyInstance
from app.models.schema import OntologyProperty
from app.repositories.class_repository import ClassRepository
from app.repositories.instance_relation_repository import InstanceRelationRepository
from app.repositories.instance_repository import InstanceRepository
from app.repositories.property_repository import PropertyRepository
from app.repositories.schema_repository import SchemaRepository
from app.schemas.extraction import InstanceRead, InstanceRelationWrite, InstanceUpdate
from app.services._utils import parse_uuid
from app.services.extraction_service import ExtractionService


class InstanceEditService:
    def __init__(self) -> None:
        self.instance_repo = InstanceRepository()
        self.relation_repo = InstanceRelationRepository()
        self.class_repo = ClassRepository()
        self.prop_repo = PropertyRepository()
        self.schema_repo = SchemaRepository()
        self._reader = ExtractionService()

    async def update_instance(
        self, session: AsyncSession, instance_id: str, body: InstanceUpdate
    ) -> InstanceRead:
        inst = await self._require_instance(session, instance_id)
        await self._set_class(session, inst, body.class_id)
        await self._replace_data_values(session, inst, body.data_values)
        await self._replace_relations(session, inst, body.relations)
        await self.schema_repo.invalidate_graph_cache(session, inst.schema_id)
        return await self._reader.get_instance(session, str(inst.id))

    async def delete_instance(self, session: AsyncSession, instance_id: str) -> None:
        inst = await self._require_instance(session, instance_id)
        schema_id = inst.schema_id
        await self.relation_repo.delete_incident(session, inst.id)
        await self.instance_repo.delete(session, inst)
        await self.schema_repo.invalidate_graph_cache(session, schema_id)

    async def _require_instance(self, session: AsyncSession, instance_id: str) -> OntologyInstance:
        inst = await self.instance_repo.get_by_id(session, parse_uuid(instance_id, field="id"))
        if not inst:
            raise AppError(ErrorCode.NOT_FOUND, message="实例不存在")
        return inst

    async def _set_class(
        self, session: AsyncSession, inst: OntologyInstance, class_id: str | None
    ) -> None:
        raw = (class_id or "").strip()
        if not raw:
            inst.class_id = None
            await session.flush()
            return
        cls = await self.class_repo.get_by_id(session, parse_uuid(raw, field="class_id"))
        if not cls or cls.schema_id != inst.schema_id:
            raise AppError(ErrorCode.VALIDATION_ERROR, message="所属类不属于当前 Schema", field="class_id")
        inst.class_id = cls.id
        await session.flush()

    async def _replace_data_values(
        self, session: AsyncSession, inst: OntologyInstance, rows: list
    ) -> None:
        used: list[uuid.UUID] = []
        values: list[InstanceDataValue] = []
        for row in rows:
            prop = await self._require_prop(session, inst, row.property_id, "data")
            if not prop.multi and prop.id in used:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    message=f"数据属性「{prop.label}」不支持多值",
                    field="data_values",
                )
            used.append(prop.id)
            values.append(
                InstanceDataValue(instance_id=inst.id, property_id=prop.id, value=row.value.strip())
            )
        await self.instance_repo.replace_data_values(session, inst.id, values)

    async def _replace_relations(
        self, session: AsyncSession, inst: OntologyInstance, rows: list[InstanceRelationWrite]
    ) -> None:
        objs: list[InstanceRelation] = []
        seen: set[tuple[uuid.UUID, uuid.UUID]] = set()
        for row in rows:
            prop = await self._require_prop(session, inst, row.property_id, "object")
            target = await self._require_target(session, inst, row.object_instance_id)
            key = (prop.id, target.id)
            if key in seen:
                continue
            seen.add(key)
            objs.append(
                InstanceRelation(
                    subject_instance_id=inst.id,
                    property_id=prop.id,
                    object_instance_id=target.id,
                )
            )
        await self.relation_repo.replace_outgoing(session, inst.id, objs)

    async def _require_target(
        self, session: AsyncSession, inst: OntologyInstance, object_instance_id: str
    ) -> OntologyInstance:
        target = await self.instance_repo.get_by_id(
            session, parse_uuid(object_instance_id, field="object_instance_id")
        )
        if not target or target.schema_id != inst.schema_id:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                message="目标实例不存在或不属于当前本体",
                field="object_instance_id",
            )
        return target

    async def _require_prop(
        self,
        session: AsyncSession,
        inst: OntologyInstance,
        property_id: str,
        kind: str,
    ) -> OntologyProperty:
        prop = await self.prop_repo.get_by_id(session, parse_uuid(property_id, field="property_id"))
        if not prop or prop.schema_id != inst.schema_id:
            raise AppError(ErrorCode.VALIDATION_ERROR, message="属性不存在或不属于当前 Schema", field="property_id")
        if prop.kind != kind:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                message="属性类型与编辑区域不匹配",
                field="property_id",
            )
        return prop
