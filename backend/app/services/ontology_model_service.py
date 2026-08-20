"""CRUD for named ontology models (Schema version + live instance counts)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ErrorCode
from app.models.ontology_model import OntologyModel
from app.repositories.class_repository import ClassRepository
from app.repositories.instance_repository import InstanceRepository
from app.repositories.ontology_model_repository import OntologyModelRepository
from app.repositories.schema_repository import SchemaRepository
from app.schemas.common import PageResponse
from app.schemas.ontology_model import OntologyModelCreate, OntologyModelRead, OntologyModelUpdate
from app.services._utils import parse_uuid


class OntologyModelService:
    def __init__(self) -> None:
        self.repo = OntologyModelRepository()
        self.schema_repo = SchemaRepository()
        self.class_repo = ClassRepository()
        self.instance_repo = InstanceRepository()

    async def list(
        self,
        session: AsyncSession,
        *,
        schema_id: str | None = None,
        search: str | None = None,
        min_instances: int = 0,
        page: int = 1,
        page_size: int = 50,
    ) -> PageResponse[OntologyModelRead]:
        sid = parse_uuid(schema_id) if schema_id else None
        if min_instances > 0:
            rows, _ = await self.repo.list(
                session, schema_id=sid, search=search, page=1, page_size=500
            )
            items = [await self._to_read(session, r) for r in rows]
            items = [x for x in items if x.instance_count >= min_instances]
            total = len(items)
            start = (page - 1) * page_size
            return PageResponse(
                items=items[start : start + page_size],
                total=total,
                page=page,
                page_size=page_size,
            )
        rows, total = await self.repo.list(
            session, schema_id=sid, search=search, page=page, page_size=page_size
        )
        items = [await self._to_read(session, r) for r in rows]
        return PageResponse(items=items, total=total, page=page, page_size=page_size)

    async def get(self, session: AsyncSession, id: str) -> OntologyModelRead:
        obj = await self.repo.get_by_id(session, parse_uuid(id))
        if not obj:
            raise AppError(ErrorCode.NOT_FOUND, message="本体模型不存在")
        return await self._to_read(session, obj)

    async def get_orm(self, session: AsyncSession, id: str) -> OntologyModel:
        obj = await self.repo.get_by_id(session, parse_uuid(id))
        if not obj:
            raise AppError(ErrorCode.NOT_FOUND, message="本体模型不存在")
        return obj

    async def create(self, session: AsyncSession, body: OntologyModelCreate) -> OntologyModelRead:
        name = body.name.strip()
        if not name:
            raise AppError(ErrorCode.VALIDATION_ERROR, message="请填写本体模型名称", field="name")
        existing = await self.repo.get_by_name(session, name)
        if existing:
            raise AppError(ErrorCode.CONFLICT, message="该本体模型名称已存在，请更换", field="name")
        sid = parse_uuid(body.schema_id)
        schema = await self.schema_repo.get_by_id(session, sid)
        if not schema:
            raise AppError(ErrorCode.GRAPH_001)
        version = body.schema_version if body.schema_version is not None else schema.version
        obj = OntologyModel(
            name=name,
            description=(body.description or "").strip(),
            schema_id=sid,
            schema_version=int(version),
        )
        obj = await self.repo.create(session, obj)
        await session.commit()
        return await self.get(session, str(obj.id))

    async def update(
        self, session: AsyncSession, id: str, body: OntologyModelUpdate
    ) -> OntologyModelRead:
        obj = await self.get_orm(session, id)
        if body.name is not None:
            name = body.name.strip()
            if not name:
                raise AppError(ErrorCode.VALIDATION_ERROR, message="请填写本体模型名称", field="name")
            dup = await self.repo.get_by_name(session, name)
            if dup and dup.id != obj.id:
                raise AppError(ErrorCode.CONFLICT, message="该本体模型名称已存在，请更换", field="name")
            obj.name = name
        if body.description is not None:
            obj.description = body.description.strip()
        await session.commit()
        return await self.get(session, id)

    async def delete(self, session: AsyncSession, id: str) -> None:
        obj = await self.get_orm(session, id)
        await self.repo.delete(session, obj)
        await session.commit()

    async def _to_read(self, session: AsyncSession, obj: OntologyModel) -> OntologyModelRead:
        schema = await self.schema_repo.get_by_id(session, obj.schema_id)
        class_count = await self.class_repo.count_by_schema(session, obj.schema_id)
        instance_count = await self.instance_repo.count_by_schema(
            session, obj.schema_id, schema_version=obj.schema_version
        )
        return OntologyModelRead(
            id=str(obj.id),
            name=obj.name,
            description=obj.description or "",
            schema_id=str(obj.schema_id),
            schema_name=schema.name if schema else "",
            schema_version=obj.schema_version,
            class_count=class_count,
            instance_count=instance_count,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )
