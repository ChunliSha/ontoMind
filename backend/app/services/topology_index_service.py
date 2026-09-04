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
        instances = await self.instance_repo.list_by_schema(
            session, sid, schema_version=version, with_details=True
        )
        relations = await self.relation_repo.list_by_schema(session, sid)
        prop_label = {p.id: p.label for p in props}
        class_label = {c.id: c.label for c in classes}
        rels_by_subject = _relations_by_subject(relations, instances, prop_label)
        indexed_inst = _indexed_instances(instances, class_label, prop_label, rels_by_subject)
        count_by_class = _count_by_class(classes, instances)
        indexed_classes = _indexed_classes(classes, props, count_by_class)
        return OntologyIndex(
            schema_id=str(schema.id),
            schema_version=version,
            classes=indexed_classes,
            instances=indexed_inst,
        )


def _relations_by_subject(relations, instances, prop_label) -> dict[uuid.UUID, list[IndexedRelation]]:
    inst_label = {item.id: item.label for item in instances}
    inst_by_id = {item.id: item for item in instances}
    rels_by_subject: dict[uuid.UUID, list[IndexedRelation]] = {}
    for rel in relations:
        if rel.subject_instance_id not in inst_by_id:
            continue
        rels_by_subject.setdefault(rel.subject_instance_id, []).append(
            IndexedRelation(
                property_label=prop_label.get(rel.property_id, str(rel.property_id)),
                object_id=str(rel.object_instance_id),
                object_label=inst_label.get(rel.object_instance_id, ""),
            )
        )
    return rels_by_subject


def _count_by_class(classes, instances) -> dict[uuid.UUID, int]:
    count_by_class: dict[uuid.UUID, int] = {cls.id: 0 for cls in classes}
    for inst in instances:
        if inst.class_id:
            count_by_class[inst.class_id] = count_by_class.get(inst.class_id, 0) + 1
    return count_by_class


def _indexed_instances(instances, class_label, prop_label, rels_by_subject) -> list[IndexedInstance]:
    indexed: list[IndexedInstance] = []
    for inst in instances:
        data_values, aliases = _instance_data(inst, prop_label)
        extra_aliases = [
            alias
            for alias in aliases
            if alias and normalize_alias(alias) != normalize_alias(inst.label)
        ]
        indexed.append(
            IndexedInstance(
                id=str(inst.id),
                class_id=str(inst.class_id) if inst.class_id else "",
                class_label=class_label.get(inst.class_id, "") if inst.class_id else "",
                label=inst.label,
                local_name=inst.local_name,
                aliases=extra_aliases,
                data_values=data_values,
                relations=rels_by_subject.get(inst.id, []),
            )
        )
    return indexed


def _instance_data(inst, prop_label) -> tuple[dict[str, str], list[str]]:
    data_values: dict[str, str] = {}
    aliases: list[str] = []
    for data_val in inst.data_values or []:
        plabel = prop_label.get(data_val.property_id, "")
        if not plabel:
            continue
        data_values[plabel] = data_val.value
        aliases.append(data_val.value)
    return data_values, aliases


def _indexed_classes(classes, props, count_by_class) -> list[IndexedClass]:
    data_by, obj_by = _props_by_class(classes, props)
    return [
        IndexedClass(
            id=str(cls.id),
            label=cls.label,
            local_name=cls.local_name,
            parent_class_id=str(cls.parent_class_id) if cls.parent_class_id else None,
            description=cls.description,
            instance_count=count_by_class.get(cls.id, 0),
            data_property_labels=data_by.get(str(cls.id), []),
            object_property_labels=obj_by.get(str(cls.id), []),
        )
        for cls in classes
    ]


def _props_by_class(classes, props) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    orm_by_id = {str(cls.id): cls for cls in classes}
    grouped: dict[str, list] = {}
    for prop in props:
        grouped.setdefault(str(prop.domain_class_id), []).append(prop)
    data_by: dict[str, list[str]] = {}
    obj_by: dict[str, list[str]] = {}
    for cls in classes:
        cid = str(cls.id)
        data_by[cid], obj_by[cid] = _walk_class_props(cid, orm_by_id, grouped)
    return data_by, obj_by


def _walk_class_props(class_id: str, orm_by_id, grouped) -> tuple[list[str], list[str]]:
    data: list[str] = []
    obj: list[str] = []
    seen: set[str] = set()
    current = class_id
    hops = 0
    while current and hops < 16:
        hops += 1
        for prop in grouped.get(current, []):
            if prop.label in seen:
                continue
            seen.add(prop.label)
            if prop.kind == "data":
                data.append(prop.label)
            elif prop.kind == "object":
                obj.append(prop.label)
        orm = orm_by_id.get(current)
        if orm is None or not orm.parent_class_id:
            break
        current = str(orm.parent_class_id)
    return data, obj
