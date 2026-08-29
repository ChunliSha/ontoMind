"""MCP / REST tool registry: all tools call KnowledgeService (no SQL)."""

from __future__ import annotations

import uuid
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ErrorCode
from app.knowledge.limits import clamp_hops, clamp_limit, clamp_nodes
from app.knowledge.service import KnowledgeService
from app.qa.agent import QaAgent

ToolHandler = Callable[[AsyncSession, dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]

ks = KnowledgeService()
qa_agent = QaAgent()


def _ok(data: Any, evidences: Any = None) -> dict[str, Any]:
    return {"ok": True, "data": data, "evidences": evidences or [], "error": None}


def _require_model_id(args: dict[str, Any]) -> str:
    mid = args.get("ontology_model_id")
    if not mid:
        raise AppError(ErrorCode.VALIDATION_ERROR, message="缺少 ontology_model_id", field="ontology_model_id")
    return str(mid)


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "list_ontology_models",
        "description": "列出可用本体模型。知识仅存在于某个模型的 schema version 切片内。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "minimum": 1, "default": 1},
                "page_size": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
            },
        },
    },
    {
        "name": "get_schema",
        "description": "返回该本体模型的 TBox 摘要（类、数据属性、对象属性 domain/range）。仅该 version 切片。",
        "inputSchema": {
            "type": "object",
            "required": ["ontology_model_id"],
            "properties": {
                "ontology_model_id": {"type": "string", "description": "本体模型 ID"},
            },
        },
    },
    {
        "name": "get_class",
        "description": "按 ID 或中文 label 查看一个类。",
        "inputSchema": {
            "type": "object",
            "required": ["ontology_model_id"],
            "properties": {
                "ontology_model_id": {"type": "string"},
                "class_id": {"type": "string"},
                "class_label": {"type": "string"},
            },
        },
    },
    {
        "name": "list_properties",
        "description": "列出类上的数据/对象属性。",
        "inputSchema": {
            "type": "object",
            "required": ["ontology_model_id"],
            "properties": {
                "ontology_model_id": {"type": "string"},
                "class_id": {"type": "string"},
                "class_label": {"type": "string"},
                "kind": {"type": "string", "enum": ["data", "object"]},
            },
        },
    },
    {
        "name": "search_instances",
        "description": "按关键词/类检索实例（标签、别名、属性值 ILIKE）。仅返回该模型 version 切片内知识。",
        "inputSchema": {
            "type": "object",
            "required": ["ontology_model_id", "q"],
            "properties": {
                "ontology_model_id": {"type": "string", "description": "本体模型 ID"},
                "q": {"type": "string"},
                "class_id": {"type": "string"},
                "class_label": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
            },
        },
    },
    {
        "name": "get_instance",
        "description": "实例详情：数据属性与关系。",
        "inputSchema": {
            "type": "object",
            "required": ["ontology_model_id", "instance_id"],
            "properties": {
                "ontology_model_id": {"type": "string"},
                "instance_id": {"type": "string"},
            },
        },
    },
    {
        "name": "list_relations",
        "description": "列出实例作为主语或宾语的关系。",
        "inputSchema": {
            "type": "object",
            "required": ["ontology_model_id", "instance_id"],
            "properties": {
                "ontology_model_id": {"type": "string"},
                "instance_id": {"type": "string"},
                "property_id": {"type": "string"},
                "property_label": {"type": "string"},
            },
        },
    },
    {
        "name": "expand_neighbors",
        "description": "受限多跳邻域（max_hops≤3，max_nodes≤200）。不要用于全图导出。",
        "inputSchema": {
            "type": "object",
            "required": ["ontology_model_id", "start_ids"],
            "properties": {
                "ontology_model_id": {"type": "string"},
                "start_ids": {"type": "array", "items": {"type": "string"}},
                "max_hops": {"type": "integer", "minimum": 1, "maximum": 3, "default": 1},
                "max_nodes": {"type": "integer", "minimum": 1, "maximum": 200, "default": 200},
                "predicates": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    {
        "name": "ask_knowledge",
        "description": "自然语言问知识库：内部走与产品问答相同的规划器。适合不会拆工具的 Agent。",
        "inputSchema": {
            "type": "object",
            "required": ["ontology_model_id", "question"],
            "properties": {
                "ontology_model_id": {"type": "string"},
                "question": {"type": "string"},
                "model_id": {"type": "string", "description": "可选 LLM 配置 ID"},
            },
        },
    },
]


async def _list_ontology_models(session: AsyncSession, args: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    page = int(args.get("page") or 1)
    page_size = clamp_limit(args.get("page_size"), default=50)
    data = await ks.list_models(session, page=page, page_size=page_size)
    return _ok(data.model_dump())


async def _get_schema(session: AsyncSession, args: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    mid = _require_model_id(args)
    data = await ks.get_schema(session, mid, caller=meta.get("caller", "mcp"), trace_id=meta.get("trace_id", ""))
    return _ok(data.model_dump())


async def _get_class(session: AsyncSession, args: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    mid = _require_model_id(args)
    data = await ks.get_class(
        session,
        mid,
        class_id=args.get("class_id"),
        class_label=args.get("class_label"),
        caller=meta.get("caller", "mcp"),
        trace_id=meta.get("trace_id", ""),
    )
    return _ok(data.model_dump())


async def _list_properties(session: AsyncSession, args: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    mid = _require_model_id(args)
    data = await ks.list_properties(
        session,
        mid,
        class_id=args.get("class_id"),
        class_label=args.get("class_label"),
        kind=args.get("kind"),
        caller=meta.get("caller", "mcp"),
        trace_id=meta.get("trace_id", ""),
    )
    return _ok([x.model_dump() for x in data])


async def _search_instances(session: AsyncSession, args: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    mid = _require_model_id(args)
    data = await ks.search_instances(
        session,
        mid,
        q=str(args.get("q") or ""),
        class_id=args.get("class_id"),
        class_label=args.get("class_label"),
        limit=clamp_limit(args.get("limit")),
        caller=meta.get("caller", "mcp"),
        trace_id=meta.get("trace_id", ""),
    )
    return _ok(
        {"items": [h.model_dump() for h in data.items], "empty_hit": data.empty_hit},
        [e.model_dump() for e in data.evidences],
    )


async def _get_instance(session: AsyncSession, args: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    mid = _require_model_id(args)
    iid = args.get("instance_id") or args.get("id")
    if not iid:
        raise AppError(ErrorCode.VALIDATION_ERROR, message="缺少 instance_id", field="instance_id")
    data = await ks.get_instance(
        session,
        mid,
        str(iid),
        caller=meta.get("caller", "mcp"),
        trace_id=meta.get("trace_id", ""),
    )
    return _ok(data.model_dump(), [e.model_dump() for e in data.evidences])


async def _list_relations(session: AsyncSession, args: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    mid = _require_model_id(args)
    iid = args.get("instance_id") or args.get("id")
    if not iid:
        raise AppError(ErrorCode.VALIDATION_ERROR, message="缺少 instance_id", field="instance_id")
    data = await ks.list_relations(
        session,
        mid,
        str(iid),
        property_id=args.get("property_id"),
        property_label=args.get("property_label"),
        caller=meta.get("caller", "mcp"),
        trace_id=meta.get("trace_id", ""),
    )
    return _ok([x.model_dump() for x in data])


async def _expand_neighbors(session: AsyncSession, args: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    mid = _require_model_id(args)
    starts = args.get("start_ids") or []
    if isinstance(starts, str):
        starts = [starts]
    data = await ks.expand_hops(
        session,
        mid,
        [str(s) for s in starts],
        max_hops=clamp_hops(args.get("max_hops") or 1),
        max_nodes=clamp_nodes(args.get("max_nodes")),
        predicates=args.get("predicates"),
        caller=meta.get("caller", "mcp"),
        trace_id=meta.get("trace_id", ""),
    )
    return _ok(data.model_dump(), [e.model_dump() for e in data.evidences])


async def _ask_knowledge(session: AsyncSession, args: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    mid = _require_model_id(args)
    question = str(args.get("question") or "").strip()
    if not question:
        raise AppError(ErrorCode.VALIDATION_ERROR, message="缺少 question", field="question")
    data = await qa_agent.ask_direct(
        session,
        mid,
        question,
        model_id=args.get("model_id"),
        caller=meta.get("caller", "mcp"),
        trace_id=meta.get("trace_id") or uuid.uuid4().hex[:16],
    )
    return _ok(data.model_dump(), [e.model_dump() for e in data.evidences])


HANDLERS: dict[str, ToolHandler] = {
    "list_ontology_models": _list_ontology_models,
    "get_schema": _get_schema,
    "get_class": _get_class,
    "list_properties": _list_properties,
    "search_instances": _search_instances,
    "get_instance": _get_instance,
    "list_relations": _list_relations,
    "expand_neighbors": _expand_neighbors,
    "ask_knowledge": _ask_knowledge,
}


async def call_tool(
    session: AsyncSession,
    name: str,
    arguments: dict[str, Any] | None,
    *,
    caller: str = "mcp",
    trace_id: str = "",
) -> dict[str, Any]:
    handler = HANDLERS.get(name)
    if not handler:
        return {"ok": False, "data": None, "evidences": [], "error": {"code": "NOT_FOUND", "message": f"未知工具: {name}"}}
    meta = {"caller": caller, "trace_id": trace_id or uuid.uuid4().hex[:16]}
    try:
        return await handler(session, arguments or {}, meta)
    except AppError as exc:
        return {
            "ok": False,
            "data": None,
            "evidences": [],
            "error": {"code": exc.code.value, "message": exc.message},
        }
