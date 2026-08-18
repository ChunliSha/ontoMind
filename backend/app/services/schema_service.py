"""SchemaService — schema/class/property CRUD, publish, TTL I/O (§5.4 / §8.3)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ErrorCode
from app.models.schema import OntologyClass, OntologyProperty, OntologySchema
from app.rdf.ttl_builder import (
    ClassSpec,
    InstanceDataValueSpec,
    InstanceRelationSpec,
    InstanceSpec,
    PropertySpec,
    build_ttl,
    label_to_local_name,
)
from app.rdf.ttl_parser import extract_entities, parse_ttl
from app.repositories.class_repository import ClassRepository
from app.repositories.instance_repository import InstanceRepository
from app.repositories.property_repository import PropertyRepository
from app.repositories.schema_repository import SchemaRepository
from app.schemas.common import PageResponse
from app.schemas.schema import (
    ClassCreate,
    ClassRead,
    ClassUpdate,
    PropertyCreate,
    PropertyRead,
    PropertyUpdate,
    SchemaCreate,
    SchemaPublishRequest,
    SchemaRead,
    SchemaUpdate,
)
from app.services._utils import parse_uuid, uid


class SchemaService:
    def __init__(self) -> None:
        self.schema_repo = SchemaRepository()
        self.class_repo = ClassRepository()
        self.prop_repo = PropertyRepository()
        self.instance_repo = InstanceRepository()

    async def list(
        self, session: AsyncSession, *, search: str | None = None, page: int = 1, page_size: int = 20
    ) -> PageResponse[SchemaRead]:
        rows, total = await self.schema_repo.list(
            session, search=search, page=page, page_size=page_size
        )
        items = []
        for r in rows:
            items.append(await self._schema_read(session, r))
        return PageResponse(items=items, total=total, page=page, page_size=page_size)

    async def create(self, session: AsyncSession, body: SchemaCreate) -> SchemaRead:
        obj = OntologySchema(
            name=body.name,
            base_iri=body.base_iri or "http://example.com/ontomind/schema#",
            status="draft",
            version=1,
            source="manual",
        )
        obj = await self.schema_repo.create(session, obj)
        return await self._schema_read(session, obj)

    async def get(self, session: AsyncSession, id: str) -> SchemaRead:
        return await self._schema_read(session, await self._get_schema(session, id))

    async def update(self, session: AsyncSession, id: str, body: SchemaUpdate) -> SchemaRead:
        obj = await self._get_schema(session, id)
        data = body.model_dump(exclude_unset=True)
        for k, v in data.items():
            setattr(obj, k, v)
        obj.updated_at = datetime.now(timezone.utc)
        await self.schema_repo.update(session, obj)
        return await self._schema_read(session, obj)

    async def publish(
        self, session: AsyncSession, id: str, body: SchemaPublishRequest
    ) -> SchemaRead:
        obj = await self._get_schema(session, id)
        obj.version = (obj.version or 1) + 1
        obj.status = "published"
        obj.change_log = body.change_log
        obj.published_at = datetime.now(timezone.utc)
        obj.updated_at = datetime.now(timezone.utc)
        await self.schema_repo.update(session, obj)
        await self.schema_repo.invalidate_graph_cache(session, obj.id)
        return await self._schema_read(session, obj)

    async def delete(self, session: AsyncSession, id: str) -> None:
        obj = await self._get_schema(session, id)
        await self.schema_repo.delete(session, obj)

    async def list_classes(self, session: AsyncSession, schema_id: str) -> list[ClassRead]:
        sid = parse_uuid(schema_id)
        await self._get_schema(session, schema_id)
        classes = await self.class_repo.list_by_schema(session, sid)
        counts = await self.class_repo.property_counts(session, sid)
        return [
            ClassRead(
                id=str(c.id),
                schema_id=str(c.schema_id),
                label=c.label,
                local_name=c.local_name,
                parent_class_id=uid(c.parent_class_id),
                description=c.description,
                source=c.source,
                cnt=counts.get(c.id, 0),
                created_at=c.created_at,
            )
            for c in classes
        ]

    async def create_class(
        self, session: AsyncSession, schema_id: str, body: ClassCreate
    ) -> ClassRead:
        schema = await self._get_schema(session, schema_id)
        existing = await self.class_repo.get_by_label(session, schema.id, body.label)
        if existing:
            raise AppError(ErrorCode.SCHEMA_001, field="label")
        local = body.local_name or label_to_local_name(body.label)
        obj = OntologyClass(
            schema_id=schema.id,
            label=body.label,
            local_name=local,
            parent_class_id=parse_uuid(body.parent_class_id) if body.parent_class_id else None,
            description=body.description,
            source="manual",
        )
        obj = await self.class_repo.create(session, obj)
        await self.schema_repo.invalidate_graph_cache(session, schema.id)
        return ClassRead(
            id=str(obj.id),
            schema_id=str(obj.schema_id),
            label=obj.label,
            local_name=obj.local_name,
            parent_class_id=uid(obj.parent_class_id),
            description=obj.description,
            source=obj.source,
            cnt=0,
            created_at=obj.created_at,
        )

    async def update_class(
        self, session: AsyncSession, class_id: str, body: ClassUpdate
    ) -> ClassRead:
        obj = await self._get_class(session, class_id)
        data = body.model_dump(exclude_unset=True)
        if "label" in data and data["label"] != obj.label:
            clash = await self.class_repo.get_by_label(session, obj.schema_id, data["label"])
            if clash:
                raise AppError(ErrorCode.SCHEMA_001, field="label")
        if "parent_class_id" in data:
            data["parent_class_id"] = (
                parse_uuid(data["parent_class_id"]) if data["parent_class_id"] else None
            )
        for k, v in data.items():
            setattr(obj, k, v)
        await self.class_repo.update(session, obj)
        await self.schema_repo.invalidate_graph_cache(session, obj.schema_id)
        counts = await self.class_repo.property_counts(session, obj.schema_id)
        return ClassRead(
            id=str(obj.id),
            schema_id=str(obj.schema_id),
            label=obj.label,
            local_name=obj.local_name,
            parent_class_id=uid(obj.parent_class_id),
            description=obj.description,
            source=obj.source,
            cnt=counts.get(obj.id, 0),
            created_at=obj.created_at,
        )

    async def delete_class(self, session: AsyncSession, class_id: str) -> None:
        obj = await self._get_class(session, class_id)
        cnt = await self.instance_repo.count_for_class(session, obj.id)
        if cnt > 0:
            raise AppError(ErrorCode.SCHEMA_004)
        schema_id = obj.schema_id
        await self.class_repo.delete(session, obj)
        await self.schema_repo.invalidate_graph_cache(session, schema_id)

    async def list_properties(self, session: AsyncSession, class_id: str) -> list[PropertyRead]:
        cls = await self._get_class(session, class_id)
        props = await self.prop_repo.list_by_class(session, cls.id)
        return [await self._prop_read(session, p) for p in props]

    async def create_property(
        self, session: AsyncSession, class_id: str, body: PropertyCreate
    ) -> PropertyRead:
        cls = await self._get_class(session, class_id)
        if body.kind == "data" and not body.datatype:
            raise AppError(ErrorCode.VALIDATION_ERROR, message="data 属性必须指定 datatype", field="datatype")
        if body.kind == "object" and not body.range_class_id:
            raise AppError(
                ErrorCode.VALIDATION_ERROR, message="object 属性必须指定 range_class_id", field="range_class_id"
            )
        existing = await self.prop_repo.get_by_label(session, cls.id, body.label)
        if existing:
            raise AppError(ErrorCode.SCHEMA_002, field="label")
        obj = OntologyProperty(
            schema_id=cls.schema_id,
            domain_class_id=cls.id,
            label=body.label,
            local_name=body.local_name or label_to_local_name(body.label),
            kind=body.kind,
            datatype=body.datatype,
            range_class_id=parse_uuid(body.range_class_id) if body.range_class_id else None,
            required=body.required,
            multi=body.multi,
            source="manual",
        )
        obj = await self.prop_repo.create(session, obj)
        await self.schema_repo.invalidate_graph_cache(session, cls.schema_id)
        return await self._prop_read(session, obj)

    async def update_property(
        self, session: AsyncSession, property_id: str, body: PropertyUpdate
    ) -> PropertyRead:
        obj = await self._get_prop(session, property_id)
        data = body.model_dump(exclude_unset=True)
        if "domain_class_id" in data and data["domain_class_id"]:
            data["domain_class_id"] = parse_uuid(data["domain_class_id"])
        if "range_class_id" in data:
            data["range_class_id"] = (
                parse_uuid(data["range_class_id"]) if data["range_class_id"] else None
            )
        if "label" in data and data["label"] != obj.label:
            domain = data.get("domain_class_id", obj.domain_class_id)
            clash = await self.prop_repo.get_by_label(session, domain, data["label"])
            if clash:
                raise AppError(ErrorCode.SCHEMA_002, field="label")
        for k, v in data.items():
            setattr(obj, k, v)
        await self.prop_repo.update(session, obj)
        await self.schema_repo.invalidate_graph_cache(session, obj.schema_id)
        return await self._prop_read(session, obj)

    async def delete_property(self, session: AsyncSession, property_id: str) -> None:
        obj = await self._get_prop(session, property_id)
        schema_id = obj.schema_id
        await self.prop_repo.delete(session, obj)
        await self.schema_repo.invalidate_graph_cache(session, schema_id)

    async def export_ttl(
        self,
        session: AsyncSession,
        schema_id: str,
        *,
        include_instances: bool = False,
        schema_version: int | None = None,
    ) -> str:
        schema = await self._get_schema(session, schema_id)
        classes = await self.class_repo.list_by_schema(session, schema.id)
        props = await self.prop_repo.list_by_schema(session, schema.id)
        id_to_ln = {c.id: (c.local_name or label_to_local_name(c.label)) for c in classes}
        class_specs = [
            ClassSpec(
                label=c.label,
                local_name=c.local_name or label_to_local_name(c.label),
                parent_local_name=id_to_ln.get(c.parent_class_id) if c.parent_class_id else None,
                description=c.description,
            )
            for c in classes
        ]
        prop_id_to_ln = {
            p.id: (p.local_name or label_to_local_name(p.label)) for p in props
        }
        prop_id_to_dt = {p.id: p.datatype for p in props}
        prop_specs = [
            PropertySpec(
                label=p.label,
                kind=p.kind,
                domain_local_name=id_to_ln.get(p.domain_class_id, "Unknown"),
                local_name=p.local_name,
                datatype=p.datatype,
                range_local_name=id_to_ln.get(p.range_class_id) if p.range_class_id else None,
            )
            for p in props
        ]

        instance_specs: list[InstanceSpec] | None = None
        if include_instances:
            version = schema_version if schema_version is not None else schema.version
            rows = await self.instance_repo.list_by_schema(
                session, schema.id, schema_version=version, with_details=True
            )
            # Only keep ABox links whose object is also in this export set
            exported_ids = {str(r.id) for r in rows}
            instance_specs = []
            for r in rows:
                class_ln = id_to_ln.get(r.class_id, "Unknown")
                data_values = [
                    InstanceDataValueSpec(
                        property_local_name=prop_id_to_ln[dv.property_id],
                        value=dv.value,
                        datatype=prop_id_to_dt.get(dv.property_id),
                    )
                    for dv in (r.data_values or [])
                    if dv.property_id in prop_id_to_ln
                ]
                relations = [
                    InstanceRelationSpec(
                        property_local_name=prop_id_to_ln.get(rel.property_id, str(rel.property_id)),
                        object_key=str(rel.object_instance_id),
                    )
                    for rel in (r.subject_relations or [])
                    if rel.property_id in prop_id_to_ln
                    and str(rel.object_instance_id) in exported_ids
                ]
                instance_specs.append(
                    InstanceSpec(
                        key=str(r.id),
                        class_local_name=class_ln,
                        label=r.label,
                        local_name=r.local_name,
                        data_values=data_values or None,
                        relations=relations or None,
                    )
                )

        return build_ttl(
            base_iri=schema.base_iri,
            classes=class_specs,
            properties=prop_specs,
            instances=instance_specs,
        )

    async def import_ttl(self, session: AsyncSession, ttl_text: str, name: str | None = None) -> SchemaRead:
        graph = parse_ttl(ttl_text)
        classes, properties = extract_entities(graph)

        async with session.begin_nested():
            schema = OntologySchema(
                name=name or "Imported Schema",
                base_iri="http://example.com/ontomind/schema#",
                status="draft",
                version=1,
                source="imported_ttl",
            )
            schema = await self.schema_repo.create(session, schema)
            ln_to_id: dict[str, object] = {}
            class_objs: list[OntologyClass] = []
            for c in classes:
                obj = OntologyClass(
                    schema_id=schema.id,
                    label=c.label,
                    local_name=c.local_name,
                    description=c.description,
                    source="manual",
                )
                class_objs.append(obj)
            await self.class_repo.bulk_create(session, class_objs)
            for obj in class_objs:
                ln_to_id[obj.local_name or obj.label] = obj.id

            # second pass parents
            for c, obj in zip(classes, class_objs, strict=True):
                if c.parent_local_name and c.parent_local_name in ln_to_id:
                    obj.parent_class_id = ln_to_id[c.parent_local_name]  # type: ignore[assignment]
            await session.flush()

            prop_objs: list[OntologyProperty] = []
            for p in properties:
                domain_id = ln_to_id.get(p.domain_local_name)
                if not domain_id:
                    continue
                range_id = ln_to_id.get(p.range_local_name) if p.range_local_name else None
                prop_objs.append(
                    OntologyProperty(
                        schema_id=schema.id,
                        domain_class_id=domain_id,  # type: ignore[arg-type]
                        label=p.label,
                        local_name=p.local_name,
                        kind=p.kind,
                        datatype=p.datatype,
                        range_class_id=range_id,  # type: ignore[arg-type]
                        source="manual",
                    )
                )
            if prop_objs:
                await self.prop_repo.bulk_create(session, prop_objs)

        return await self._schema_read(session, schema)

    async def _schema_read(self, session: AsyncSession, obj: OntologySchema) -> SchemaRead:
        return SchemaRead(
            id=str(obj.id),
            name=obj.name,
            base_iri=obj.base_iri,
            status=obj.status,  # type: ignore[arg-type]
            version=obj.version,
            change_log=obj.change_log,
            source=obj.source,
            class_count=await self.class_repo.count_by_schema(session, obj.id),
            property_count=await self.prop_repo.count_by_schema(session, obj.id),
            published_at=obj.published_at,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )

    async def _prop_read(self, session: AsyncSession, obj: OntologyProperty) -> PropertyRead:
        range_label = None
        if obj.range_class_id:
            rc = await self.class_repo.get_by_id(session, obj.range_class_id)
            range_label = rc.label if rc else None
        conf = float(obj.confidence) if obj.confidence is not None else None
        return PropertyRead(
            id=str(obj.id),
            schema_id=str(obj.schema_id),
            domain_class_id=str(obj.domain_class_id),
            label=obj.label,
            local_name=obj.local_name,
            kind=obj.kind,  # type: ignore[arg-type]
            datatype=obj.datatype,
            range_class_id=uid(obj.range_class_id),
            range_class_label=range_label,
            required=obj.required,
            multi=obj.multi,
            source=obj.source if obj.source in ("manual", "ai") else "manual",  # type: ignore[arg-type]
            confidence=conf,
            created_at=obj.created_at,
        )

    async def _get_schema(self, session: AsyncSession, id: str) -> OntologySchema:
        obj = await self.schema_repo.get_by_id(session, parse_uuid(id))
        if not obj:
            raise AppError(ErrorCode.GRAPH_001)
        return obj

    async def _get_class(self, session: AsyncSession, id: str) -> OntologyClass:
        obj = await self.class_repo.get_by_id(session, parse_uuid(id))
        if not obj:
            raise AppError(ErrorCode.NOT_FOUND, message="类不存在")
        return obj

    async def _get_prop(self, session: AsyncSession, id: str) -> OntologyProperty:
        obj = await self.prop_repo.get_by_id(session, parse_uuid(id))
        if not obj:
            raise AppError(ErrorCode.NOT_FOUND, message="属性不存在")
        return obj
