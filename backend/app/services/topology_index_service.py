"""Load OntologyIndex from schema classes + instances (P1)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ErrorCode
from app.repositories.class_repository import ClassRepository
from app.repositories.instance_relation_repository import InstanceRelationRepository
from app.repositories.instance_repository import InstanceRepository
from app.repositories.property_repository import PropertyRepository
from app.repositories.schema_repository import SchemaRepository
from app.services._utils import parse_uuid
from app.topology.index import IndexedClass, IndexedInstance, IndexedRelation, OntologyIndex
from app.topology.normalize import normalize_alias


class TopologyIndexService:
    def __init__(self) -> None:
        self.schema_repo = SchemaRepository()
        self.class_repo = ClassRepository()
        self.prop_repo = PropertyRepository()
        self.instance_repo = InstanceRepository()
        self.relation_repo = InstanceRelationRepository()

    async def build_index(
        self,
        session: AsyncSession,
        schema_id: str,
        *,
        schema_version: int | None = None,
    ) -> OntologyIndex:
        sid = parse_uuid(schema_id)
        schema = await self.schema_repo.get_by_id(session, sid)
        if not schema:
            raise AppError(ErrorCode.GRAPH_001)
        version = schema_version if schema_version is not None else schema.version

        classes = await self.class_repo.list_by_schema(session, sid)
        props = await self.prop_repo.list_by_schema(session, sid)
        prop_label = {p.id: p.label for p in props}
        instances = await self.instance_repo.list_by_schema(
            session, sid, schema_version=version, with_details=True
        )
        relations = await self.relation_repo.list_by_schema(session, sid)

        class_label = {c.id: c.label for c in classes}
        inst_label = {i.id: i.label for i in instances}
        inst_by_id = {i.id: i for i in instances}

        rels_by_subject: dict[uuid.UUID, list[IndexedRelation]] = {}
        for rel in relations:
            if rel.subject_instance_id not in inst_by_id:
                continue
            obj_label = inst_label.get(rel.object_instance_id, "")
            rels_by_subject.setdefault(rel.subject_instance_id, []).append(
                IndexedRelation(
                    property_label=prop_label.get(rel.property_id, str(rel.property_id)),
                    object_id=str(rel.object_instance_id),
                    object_label=obj_label,
                )
            )

        indexed_inst: list[IndexedInstance] = []
        count_by_class: dict[uuid.UUID, int] = {c.id: 0 for c in classes}
        for inst in instances:
            count_by_class[inst.class_id] = count_by_class.get(inst.class_id, 0) + 1
            data_values: dict[str, str] = {}
            aliases: list[str] = []
            for dv in inst.data_values or []:
                plabel = prop_label.get(dv.property_id, "")
                if not plabel:
                    continue
                data_values[plabel] = dv.value
                aliases.append(dv.value)
            indexed_inst.append(
                IndexedInstance(
                    id=str(inst.id),
                    class_id=str(inst.class_id),
                    class_label=class_label.get(inst.class_id, ""),
                    label=inst.label,
                    local_name=inst.local_name,
                    aliases=[a for a in aliases if a and normalize_alias(a) != normalize_alias(inst.label)],
                    data_values=data_values,
                    relations=rels_by_subject.get(inst.id, []),
                )
            )

        indexed_classes = [
            IndexedClass(
                id=str(c.id),
                label=c.label,
                local_name=c.local_name,
                parent_class_id=str(c.parent_class_id) if c.parent_class_id else None,
                description=c.description,
                instance_count=count_by_class.get(c.id, 0),
            )
            for c in classes
        ]
        return OntologyIndex(
            schema_id=str(schema.id),
            schema_version=version,
            classes=indexed_classes,
            instances=indexed_inst,
        )
