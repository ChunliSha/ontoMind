"""MCP API key and service repositories."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mcp import McpApiKey, McpService


class McpApiKeyRepository:
    async def list_active(self, session: AsyncSession) -> list[McpApiKey]:
        result = await session.execute(
            select(McpApiKey)
            .where(McpApiKey.revoked_at.is_(None))
            .order_by(McpApiKey.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, session: AsyncSession, id: uuid.UUID) -> McpApiKey | None:
        result = await session.execute(select(McpApiKey).where(McpApiKey.id == id))
        return result.scalar_one_or_none()

    async def get_by_hash(self, session: AsyncSession, key_hash: str) -> McpApiKey | None:
        result = await session.execute(
            select(McpApiKey).where(McpApiKey.key_hash == key_hash, McpApiKey.revoked_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def create(self, session: AsyncSession, obj: McpApiKey) -> McpApiKey:
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return obj

    async def delete(self, session: AsyncSession, obj: McpApiKey) -> None:
        await session.delete(obj)
        await session.flush()


class McpServiceRepository:
    async def list(self, session: AsyncSession) -> list[McpService]:
        result = await session.execute(select(McpService).order_by(McpService.updated_at.desc()))
        return list(result.scalars().all())

    async def list_by_ontology(self, session: AsyncSession, ontology_model_id: uuid.UUID) -> list[McpService]:
        result = await session.execute(
            select(McpService)
            .where(McpService.ontology_model_id == ontology_model_id)
            .order_by(McpService.updated_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, session: AsyncSession, id: uuid.UUID) -> McpService | None:
        result = await session.execute(select(McpService).where(McpService.id == id))
        return result.scalar_one_or_none()

    async def get_by_name(self, session: AsyncSession, name: str) -> McpService | None:
        result = await session.execute(select(McpService).where(McpService.name == name))
        return result.scalar_one_or_none()

    async def create(self, session: AsyncSession, obj: McpService) -> McpService:
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return obj

    async def delete(self, session: AsyncSession, obj: McpService) -> None:
        await session.delete(obj)
        await session.flush()
