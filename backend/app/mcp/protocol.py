"""MCP JSON-RPC 2.0 subset: initialize, tools/list, tools/call, ping."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.tools import TOOL_SCHEMAS, call_tool

PROTOCOL_VERSION = "2024-11-05"
SUPPORTED_PROTOCOL_VERSIONS = (
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    "2025-11-25",
)
SERVER_INFO = {"name": "KnowMind", "version": "0.1.0"}


def negotiate_protocol_version(requested: str | None) -> str:
    ver = (requested or "").strip()
    if ver in SUPPORTED_PROTOCOL_VERSIONS:
        return ver
    return "2025-03-26" if ver else PROTOCOL_VERSION


def bind_tool_schemas(
    *,
    ontology_model_id: str | None = None,
    allowed_tools: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Filter published tools and hide ontology_model_id when the URL already binds one."""
    out: list[dict[str, Any]] = []
    for raw in TOOL_SCHEMAS:
        name = str(raw.get("name") or "")
        if allowed_tools is not None and name not in allowed_tools:
            continue
        schema = json.loads(json.dumps(raw))
        if ontology_model_id and name != "list_ontology_models":
            inp = schema.setdefault("inputSchema", {"type": "object", "properties": {}})
            required = [x for x in (inp.get("required") or []) if x != "ontology_model_id"]
            inp["required"] = required
            props = inp.setdefault("properties", {})
            if "ontology_model_id" in props:
                props["ontology_model_id"] = {
                    **props["ontology_model_id"],
                    "description": f"已绑定本体，可省略。默认 {ontology_model_id}",
                    "default": ontology_model_id,
                }
        out.append(schema)
    return out


def apply_bound_ontology(arguments: dict[str, Any] | None, ontology_model_id: str | None) -> dict[str, Any]:
    args = dict(arguments or {})
    if ontology_model_id and not str(args.get("ontology_model_id") or "").strip():
        args["ontology_model_id"] = ontology_model_id
    return args


async def handle_rpc(
    session: AsyncSession,
    message: dict[str, Any],
    *,
    caller: str = "mcp",
    ontology_model_id: str | None = None,
    allowed_tools: list[str] | None = None,
    ontology_label: str | None = None,
) -> dict[str, Any] | None:
    """Handle one JSON-RPC request. Notifications return None."""
    method = message.get("method")
    msg_id = message.get("id")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    if method and str(method).startswith("notifications/"):
        return None
    if method == "initialize":
        return _handle_initialize(msg_id, params, ontology_model_id, ontology_label)
    if method == "ping":
        return _result(msg_id, {})
    if method == "tools/list":
        return _result(
            msg_id,
            {
                "tools": bind_tool_schemas(
                    ontology_model_id=ontology_model_id,
                    allowed_tools=allowed_tools,
                )
            },
        )
    if method == "tools/call":
        return await _handle_tools_call(
            session, msg_id, params, caller, ontology_model_id, allowed_tools
        )
    return _error(msg_id, -32601, f"Method not found: {method}")


def _handle_initialize(msg_id, params, ontology_model_id, ontology_label) -> dict[str, Any]:
    requested = params.get("protocolVersion") if isinstance(params, dict) else None
    instructions = "KnowMind 知识 MCP。工具参数需要 ontology_model_id，或先调用 list_ontology_models。"
    if ontology_model_id:
        label = ontology_label or ontology_model_id
        instructions = (
            f"本连接已绑定本体「{label}」（{ontology_model_id}）。"
            "调用工具时无需再传 ontology_model_id。"
        )
    return _result(
        msg_id,
        {
            "protocolVersion": negotiate_protocol_version(str(requested) if requested else None),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": instructions,
        },
    )


async def _handle_tools_call(
    session, msg_id, params, caller, ontology_model_id, allowed_tools
) -> dict[str, Any]:
    name = str(params.get("name") or "")
    if allowed_tools is not None and name not in allowed_tools:
        return _error(msg_id, -32601, f"Method not found: {name}")
    arguments = apply_bound_ontology(
        params.get("arguments") if isinstance(params.get("arguments"), dict) else {},
        ontology_model_id,
    )
    payload = await call_tool(session, name, arguments, caller=caller)
    text = json.dumps(payload, ensure_ascii=False)
    is_error = not payload.get("ok", False)
    return _result(
        msg_id,
        {
            "content": [{"type": "text", "text": text}],
            "isError": is_error,
            "structuredContent": payload,
        },
    )


def _result(msg_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}
