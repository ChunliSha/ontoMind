"""Register KnowledgeService tools on official FastMCP when the SDK is installed."""

from __future__ import annotations

from typing import Any

from app.db.session import AsyncSessionLocal
from app.mcp.tools import call_tool


def register_fastmcp(mcp: Any) -> None:
    @mcp.tool(name="list_ontology_models", description="列出可用本体模型。")
    async def list_ontology_models(page: int = 1, page_size: int = 50) -> dict:
        async with AsyncSessionLocal() as session:
            out = await call_tool(session, "list_ontology_models", {"page": page, "page_size": page_size})
            await session.commit()
            return out

    @mcp.tool(name="get_schema", description="TBox 摘要。仅该模型 version 切片。")
    async def get_schema(ontology_model_id: str) -> dict:
        async with AsyncSessionLocal() as session:
            out = await call_tool(session, "get_schema", {"ontology_model_id": ontology_model_id})
            await session.commit()
            return out

    @mcp.tool(name="get_class", description="查看一个类。")
    async def get_class(
        ontology_model_id: str, class_id: str | None = None, class_label: str | None = None
    ) -> dict:
        async with AsyncSessionLocal() as session:
            out = await call_tool(
                session,
                "get_class",
                {"ontology_model_id": ontology_model_id, "class_id": class_id, "class_label": class_label},
            )
            await session.commit()
            return out

    @mcp.tool(name="list_properties", description="列出类上的属性。")
    async def list_properties(
        ontology_model_id: str,
        class_id: str | None = None,
        class_label: str | None = None,
        kind: str | None = None,
    ) -> dict:
        async with AsyncSessionLocal() as session:
            out = await call_tool(
                session,
                "list_properties",
                {
                    "ontology_model_id": ontology_model_id,
                    "class_id": class_id,
                    "class_label": class_label,
                    "kind": kind,
                },
            )
            await session.commit()
            return out

    @mcp.tool(name="search_instances", description="按关键词检索实例。")
    async def search_instances(
        ontology_model_id: str,
        q: str,
        class_id: str | None = None,
        class_label: str | None = None,
        limit: int = 20,
    ) -> dict:
        async with AsyncSessionLocal() as session:
            out = await call_tool(
                session,
                "search_instances",
                {
                    "ontology_model_id": ontology_model_id,
                    "q": q,
                    "class_id": class_id,
                    "class_label": class_label,
                    "limit": limit,
                },
            )
            await session.commit()
            return out

    @mcp.tool(name="get_instance", description="实例详情。")
    async def get_instance(ontology_model_id: str, instance_id: str) -> dict:
        async with AsyncSessionLocal() as session:
            out = await call_tool(
                session,
                "get_instance",
                {"ontology_model_id": ontology_model_id, "instance_id": instance_id},
            )
            await session.commit()
            return out

    @mcp.tool(name="list_relations", description="列出实例关系。")
    async def list_relations(
        ontology_model_id: str,
        instance_id: str,
        property_id: str | None = None,
        property_label: str | None = None,
    ) -> dict:
        async with AsyncSessionLocal() as session:
            out = await call_tool(
                session,
                "list_relations",
                {
                    "ontology_model_id": ontology_model_id,
                    "instance_id": instance_id,
                    "property_id": property_id,
                    "property_label": property_label,
                },
            )
            await session.commit()
            return out

    @mcp.tool(name="expand_neighbors", description="受限多跳邻域。")
    async def expand_neighbors(
        ontology_model_id: str,
        start_ids: list[str],
        max_hops: int = 1,
        max_nodes: int = 200,
        predicates: list[str] | None = None,
    ) -> dict:
        async with AsyncSessionLocal() as session:
            out = await call_tool(
                session,
                "expand_neighbors",
                {
                    "ontology_model_id": ontology_model_id,
                    "start_ids": start_ids,
                    "max_hops": max_hops,
                    "max_nodes": max_nodes,
                    "predicates": predicates,
                },
            )
            await session.commit()
            return out

    @mcp.tool(name="ask_knowledge", description="自然语言问知识库（内部走同一规划器）。")
    async def ask_knowledge(ontology_model_id: str, question: str, model_id: str | None = None) -> dict:
        async with AsyncSessionLocal() as session:
            out = await call_tool(
                session,
                "ask_knowledge",
                {"ontology_model_id": ontology_model_id, "question": question, "model_id": model_id},
            )
            await session.commit()
            return out
