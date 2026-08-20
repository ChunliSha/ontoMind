"""Persistence for business-logic topology graphs."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.topology import BusinessLogicTopology, BusinessLogicTopologyNode


class TopologyRepository:
    async def get_by_id(
        self, session: AsyncSession, id: uuid.UUID
    ) -> BusinessLogicTopology | None:
        result = await session.execute(
            select(BusinessLogicTopology)
            .options(selectinload(BusinessLogicTopology.nodes))
            .where(BusinessLogicTopology.id == id)
        )
        return result.scalar_one_or_none()

    async def get_by_task(
        self, session: AsyncSession, task_id: uuid.UUID
    ) -> BusinessLogicTopology | None:
        result = await session.execute(
            select(BusinessLogicTopology)
            .options(selectinload(BusinessLogicTopology.nodes))
            .where(BusinessLogicTopology.extraction_task_id == task_id)
            .order_by(BusinessLogicTopology.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_by_schema(
        self,
        session: AsyncSession,
        schema_id: uuid.UUID | None = None,
        *,
        schema_version: int | None = None,
        ontology_model_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[BusinessLogicTopology]:
        stmt = select(BusinessLogicTopology).order_by(BusinessLogicTopology.created_at.desc()).limit(limit)
        if schema_id:
            stmt = stmt.where(BusinessLogicTopology.schema_id == schema_id)
        if schema_version is not None:
            stmt = stmt.where(BusinessLogicTopology.schema_version == schema_version)
        if ontology_model_id:
            stmt = stmt.where(BusinessLogicTopology.ontology_model_id == ontology_model_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self, session: AsyncSession, obj: BusinessLogicTopology
    ) -> BusinessLogicTopology:
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return obj

    async def delete(self, session: AsyncSession, obj: BusinessLogicTopology) -> None:
        await session.delete(obj)
        await session.flush()

    async def replace_nodes(
        self,
        session: AsyncSession,
        topology: BusinessLogicTopology,
        nodes: list[BusinessLogicTopologyNode],
    ) -> None:
        topology.nodes.clear()
        await session.flush()
        for node in nodes:
            node.topology_id = topology.id
            topology.nodes.append(node)
        await session.flush()
