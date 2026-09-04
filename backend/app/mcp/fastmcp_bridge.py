"""Register KnowledgeService tools on official FastMCP when the SDK is installed."""

from __future__ import annotations

from typing import Any

from app.db.session import AsyncSessionLocal
from app.mcp.tools import call_tool


async def _call_with_session(name: str, arguments: dict[str, Any]) -> dict:
    async with AsyncSessionLocal() as session:
        out = await call_tool(session, name, arguments)
        await session.commit()
        return out


async def list_ontology_models(page: int = 1, page_size: int = 50) -> dict:
    return await _call_with_session(
        "list_ontology_models", {"page": page, "page_size": page_size}
    )


async def get_schema(ontology_model_id: str) -> dict:
    return await _call_with_session("get_schema", {"ontology_model_id": ontology_model_id})


async def get_class(
    ontology_model_id: str, class_id: str | None = None, class_label: str | None = None
) -> dict:
    return await _call_with_session(
        "get_class",
        {
            "ontology_model_id": ontology_model_id,
            "class_id": class_id,
            "class_label": class_label,
        },
    )


async def list_properties(
    ontology_model_id: str,
    class_id: str | None = None,
    class_label: str | None = None,
    kind: str | None = None,
) -> dict:
    return await _call_with_session(
        "list_properties",
        {
            "ontology_model_id": ontology_model_id,
            "class_id": class_id,
            "class_label": class_label,
            "kind": kind,
        },
    )


async def search_instances(
    ontology_model_id: str,
    q: str,
    class_id: str | None = None,
    class_label: str | None = None,
    limit: int = 20,
) -> dict:
    return await _call_with_session(
        "search_instances",
        {
            "ontology_model_id": ontology_model_id,
            "q": q,
            "class_id": class_id,
            "class_label": class_label,
            "limit": limit,
        },
    )


async def get_instance(ontology_model_id: str, instance_id: str) -> dict:
    return await _call_with_session(
        "get_instance",
        {"ontology_model_id": ontology_model_id, "instance_id": instance_id},
    )


async def list_relations(
    ontology_model_id: str,
    instance_id: str,
    property_id: str | None = None,
    property_label: str | None = None,
) -> dict:
    return await _call_with_session(
        "list_relations",
        {
            "ontology_model_id": ontology_model_id,
            "instance_id": instance_id,
            "property_id": property_id,
            "property_label": property_label,
        },
    )


async def expand_neighbors(
    ontology_model_id: str,
    start_ids: list[str],
    max_hops: int = 1,
    max_nodes: int = 200,
    predicates: list[str] | None = None,
) -> dict:
    return await _call_with_session(
        "expand_neighbors",
        {
            "ontology_model_id": ontology_model_id,
            "start_ids": start_ids,
            "max_hops": max_hops,
            "max_nodes": max_nodes,
            "predicates": predicates,
        },
    )


async def ask_knowledge(
    ontology_model_id: str, question: str, model_id: str | None = None
) -> dict:
    return await _call_with_session(
        "ask_knowledge",
        {
            "ontology_model_id": ontology_model_id,
            "question": question,
            "model_id": model_id,
        },
    )


_TOOL_BINDINGS = (
    ("list_ontology_models", "列出可用本体模型。", list_ontology_models),
    ("get_schema", "TBox 摘要。仅该模型 version 切片。", get_schema),
    ("get_class", "查看一个类。", get_class),
    ("list_properties", "列出类上的属性。", list_properties),
    ("search_instances", "按关键词检索实例。", search_instances),
    ("get_instance", "实例详情。", get_instance),
    ("list_relations", "列出实例关系。", list_relations),
    ("expand_neighbors", "受限多跳邻域。", expand_neighbors),
    ("ask_knowledge", "自然语言问知识库（内部走同一规划器）。", ask_knowledge),
)


def register_fastmcp(mcp: Any) -> None:
    for name, description, func in _TOOL_BINDINGS:
        mcp.tool(name=name, description=description)(func)
