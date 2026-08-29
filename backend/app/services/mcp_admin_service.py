"""MCP API key issuance and service registry."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ErrorCode
from app.mcp.auth import hash_mcp_key
from app.mcp.tools import TOOL_SCHEMAS
from app.models.mcp import McpApiKey, McpService
from app.repositories.mcp_repository import McpApiKeyRepository, McpServiceRepository
from app.repositories.ontology_model_repository import OntologyModelRepository
from app.schemas.mcp_admin import (
    McpApiKeyCreated,
    McpApiKeyRead,
    McpPublishedTool,
    McpServiceCreate,
    McpServiceRead,
    McpServiceUpdate,
)
from app.services._utils import parse_uuid, uid

_PUBLISHED = {str(t.get("name") or "") for t in TOOL_SCHEMAS if t.get("name")}


class McpAdminService:
    def __init__(self) -> None:
        self.keys = McpApiKeyRepository()
        self.services = McpServiceRepository()
        self.models = OntologyModelRepository()

    def published_tools(self) -> list[McpPublishedTool]:
        return [
            McpPublishedTool(name=str(t.get("name") or ""), description=str(t.get("description") or ""))
            for t in TOOL_SCHEMAS
            if t.get("name")
        ]

    async def list_keys(self, session: AsyncSession) -> list[McpApiKeyRead]:
        rows = await self.keys.list_active(session)
        return [self._key_read(r) for r in rows]

    async def create_key(self, session: AsyncSession, *, name: str = "") -> McpApiKeyCreated:
        raw = "omk_" + secrets.token_urlsafe(32)
        obj = McpApiKey(
            name=(name or "").strip() or "未命名 Key",
            key_prefix=raw[:10],
            key_hash=hash_mcp_key(raw),
        )
        obj = await self.keys.create(session, obj)
        data = self._key_read(obj)
        return McpApiKeyCreated(**data.model_dump(), api_key=raw)

    async def delete_key(self, session: AsyncSession, key_id: str) -> None:
        obj = await self.keys.get_by_id(session, parse_uuid(key_id, field="id"))
        if not obj or obj.revoked_at is not None:
            raise AppError(ErrorCode.NOT_FOUND, message="API Key 不存在")
        obj.revoked_at = datetime.now(timezone.utc)
        await session.flush()

    async def list_services(self, session: AsyncSession) -> list[McpServiceRead]:
        rows = await self.services.list(session)
        return [await self._service_read(session, r) for r in rows]

    async def create_service(self, session: AsyncSession, body: McpServiceCreate) -> McpServiceRead:
        name = body.name.strip()
        if await self.services.get_by_name(session, name):
            raise AppError(ErrorCode.CONFLICT, message="该 MCP 服务名称已存在", field="name")
        mid = await self._require_model(session, body.ontology_model_id)
        if not mid:
            raise AppError(ErrorCode.KNOWLEDGE_001)
        tools = self._validate_tools(body.tool_names)
        obj = McpService(
            name=name,
            ontology_model_id=mid,
            url=(body.url or "").strip(),
            tool_names=tools,
            description=(body.description or "").strip(),
        )
        obj = await self.services.create(session, obj)
        return await self._service_read(session, obj)

    async def update_service(
        self, session: AsyncSession, service_id: str, body: McpServiceUpdate
    ) -> McpServiceRead:
        obj = await self.services.get_by_id(session, parse_uuid(service_id, field="id"))
        if not obj:
            raise AppError(ErrorCode.NOT_FOUND, message="MCP 服务不存在")
        if body.name is not None:
            name = body.name.strip()
            other = await self.services.get_by_name(session, name)
            if other and other.id != obj.id:
                raise AppError(ErrorCode.CONFLICT, message="该 MCP 服务名称已存在", field="name")
            obj.name = name
        if body.ontology_model_id is not None:
            obj.ontology_model_id = await self._require_model(session, body.ontology_model_id or None)
        if body.url is not None:
            obj.url = body.url.strip()
        if body.tool_names is not None:
            obj.tool_names = self._validate_tools(body.tool_names)
        if body.description is not None:
            obj.description = body.description.strip()
        obj.updated_at = datetime.now(timezone.utc)
        await session.flush()
        # onupdate=func.now() expires updated_at; refresh avoids async lazy-load 500
        await session.refresh(obj)
        return await self._service_read(session, obj)

    async def delete_service(self, session: AsyncSession, service_id: str) -> None:
        obj = await self.services.get_by_id(session, parse_uuid(service_id, field="id"))
        if not obj:
            raise AppError(ErrorCode.NOT_FOUND, message="MCP 服务不存在")
        await self.services.delete(session, obj)

    async def _require_model(self, session: AsyncSession, ontology_model_id: str | None):
        if not ontology_model_id:
            return None
        mid = parse_uuid(ontology_model_id, field="ontology_model_id")
        model = await self.models.get_by_id(session, mid)
        if not model:
            raise AppError(ErrorCode.KNOWLEDGE_001)
        return mid

    def _validate_tools(self, names: list[str] | None) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for n in names or []:
            name = str(n).strip()
            if not name or name in seen:
                continue
            if name not in _PUBLISHED:
                raise AppError(ErrorCode.VALIDATION_ERROR, message=f"未发布的 MCP 工具：{name}", field="tool_names")
            seen.add(name)
            out.append(name)
        return out

    @staticmethod
    def _key_read(obj: McpApiKey) -> McpApiKeyRead:
        return McpApiKeyRead(
            id=str(obj.id),
            name=obj.name or "",
            key_prefix=obj.key_prefix,
            created_at=obj.created_at,
            last_used_at=obj.last_used_at,
        )

    async def _service_read(self, session: AsyncSession, obj: McpService) -> McpServiceRead:
        model_name = None
        if obj.ontology_model_id:
            model = await self.models.get_by_id(session, obj.ontology_model_id)
            model_name = model.name if model else None
        tools = obj.tool_names if isinstance(obj.tool_names, list) else []
        return McpServiceRead(
            id=str(obj.id),
            name=obj.name,
            ontology_model_id=uid(obj.ontology_model_id),
            ontology_model_name=model_name,
            url=obj.url or "",
            tool_names=[str(x) for x in tools],
            description=obj.description or "",
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )
