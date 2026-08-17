"""MappingService — field mapping CRUD + candidates (§8.5)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ErrorCode
from app.models.mapping import FieldMapping, FieldMappingBinding
from app.repositories.class_repository import ClassRepository
from app.repositories.mapping_repository import MappingRepository
from app.repositories.property_repository import PropertyRepository
from app.repositories.table_repository import TableRepository
from app.schemas.mapping import (
    MappingBindingRead,
    MappingCreate,
    MappingRead,
    SourceFieldRead,
    TargetPropertyRead,
)
from app.services._utils import parse_uuid, uid

# rough type compatibility for MAPPING_002
_COMPAT = {
    "xsd:string": {"varchar", "text", "character varying", "string", "char", "nvarchar"},
    "xsd:int": {"int", "integer", "bigint", "smallint", "serial"},
    "xsd:decimal": {"numeric", "decimal", "float", "double", "real"},
    "xsd:boolean": {"bool", "boolean"},
    "xsd:dateTime": {"timestamp", "timestamptz", "datetime", "date"},
    "xsd:json": {"json", "jsonb", "text"},
}


class MappingService:
    def __init__(self) -> None:
        self.repo = MappingRepository()
        self.table_repo = TableRepository()
        self.prop_repo = PropertyRepository()
        self.class_repo = ClassRepository()

    async def source_fields(self, session: AsyncSession, table_id: str) -> list[SourceFieldRead]:
        table = await self.table_repo.get_by_id(session, parse_uuid(table_id))
        if not table:
            raise AppError(ErrorCode.NOT_FOUND, message="源表不存在")
        return [
            SourceFieldRead(
                column_name=c.column_name,
                data_type=c.data_type,
                is_primary_key=c.is_primary_key,
                ordinal=c.ordinal,
            )
            for c in sorted(table.columns or [], key=lambda x: x.ordinal)
        ]

    async def target_properties(
        self, session: AsyncSession, class_id: str
    ) -> list[TargetPropertyRead]:
        cls = await self.class_repo.get_by_id(session, parse_uuid(class_id))
        if not cls:
            raise AppError(ErrorCode.NOT_FOUND, message="类不存在")
        props = await self.prop_repo.list_by_class(session, cls.id)
        items: list[TargetPropertyRead] = [
            TargetPropertyRead(
                id=None,
                label="实例 URI",
                kind="instance_uri",
                datatype=None,
                target_kind="instance_uri",
            )
        ]
        for p in props:
            items.append(
                TargetPropertyRead(
                    id=str(p.id),
                    label=p.label,
                    kind=p.kind,  # type: ignore[arg-type]
                    datatype=p.datatype,
                    target_kind="property",
                )
            )
        return items

    async def list(
        self,
        session: AsyncSession,
        *,
        schema_id: str | None = None,
        class_id: str | None = None,
    ) -> list[MappingRead]:
        rows = await self.repo.list(
            session,
            schema_id=parse_uuid(schema_id) if schema_id else None,
            class_id=parse_uuid(class_id) if class_id else None,
        )
        return [self._to_read(r) for r in rows]

    async def save(self, session: AsyncSession, body: MappingCreate) -> MappingRead:
        if not any(b.target_kind == "instance_uri" for b in body.bindings):
            raise AppError(ErrorCode.MAPPING_001)

        table = await self.table_repo.get_by_id(session, parse_uuid(body.table_id))
        if not table:
            raise AppError(ErrorCode.NOT_FOUND, message="源表不存在")
        col_types = {c.column_name: c.data_type.lower() for c in (table.columns or [])}

        for b in body.bindings:
            if b.target_kind == "property" and b.target_property_id:
                prop = await self.prop_repo.get_by_id(session, parse_uuid(b.target_property_id))
                if prop and prop.kind == "data" and prop.datatype:
                    src = col_types.get(b.source_column, "")
                    if not self._compatible(prop.datatype, src):
                        raise AppError(ErrorCode.MAPPING_002, field=b.source_column)

        existing = await self.repo.get_by_class_table(
            session, parse_uuid(body.class_id), parse_uuid(body.table_id)
        )
        if existing:
            mapping = existing
            mapping.updated_at = datetime.now(timezone.utc)
            bindings = [
                FieldMappingBinding(
                    target_kind=b.target_kind,
                    target_property_id=(
                        parse_uuid(b.target_property_id) if b.target_property_id else None
                    ),
                    source_column=b.source_column,
                )
                for b in body.bindings
            ]
            mapping = await self.repo.replace_bindings(session, mapping, bindings)
        else:
            mapping = FieldMapping(
                schema_id=parse_uuid(body.schema_id),
                class_id=parse_uuid(body.class_id),
                table_id=parse_uuid(body.table_id),
            )
            mapping = await self.repo.create(session, mapping)
            bindings = [
                FieldMappingBinding(
                    mapping_id=mapping.id,
                    target_kind=b.target_kind,
                    target_property_id=(
                        parse_uuid(b.target_property_id) if b.target_property_id else None
                    ),
                    source_column=b.source_column,
                )
                for b in body.bindings
            ]
            mapping = await self.repo.replace_bindings(session, mapping, bindings)

        mapping = await self.repo.get_by_id(session, mapping.id)
        assert mapping is not None
        return self._to_read(mapping)

    @staticmethod
    def _compatible(datatype: str, source_type: str) -> bool:
        allowed = _COMPAT.get(datatype, set())
        if not allowed:
            return True
        return any(a in source_type for a in allowed)

    @staticmethod
    def _to_read(obj: FieldMapping) -> MappingRead:
        return MappingRead(
            id=str(obj.id),
            schema_id=str(obj.schema_id),
            class_id=str(obj.class_id),
            table_id=str(obj.table_id),
            bindings=[
                MappingBindingRead(
                    id=str(b.id),
                    target_kind=b.target_kind,
                    target_property_id=uid(b.target_property_id),
                    source_column=b.source_column,
                )
                for b in (obj.bindings or [])
            ],
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )
