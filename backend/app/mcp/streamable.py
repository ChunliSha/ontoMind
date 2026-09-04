"""Cursor-compatible MCP Streamable HTTP (JSON responses)."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.auth import assert_mcp_key
from app.mcp.protocol import handle_rpc
from app.repositories.mcp_repository import McpServiceRepository
from app.repositories.ontology_model_repository import OntologyModelRepository
from app.services._utils import parse_uuid

_services = McpServiceRepository()
_models = OntologyModelRepository()


def extract_ontology_id(request: Request) -> str | None:
    q = request.query_params
    raw = (q.get("ontology_id") or q.get("ontology_model_id") or "").strip()
    return raw or None


async def resolve_binding(
    session: AsyncSession, ontology_id: str | None
) -> tuple[str | None, str | None, list[str] | None]:
    """Return (ontology_model_id, label, allowed_tool_names)."""
    if not ontology_id:
        return None, None, None
    mid = parse_uuid(ontology_id, field="ontology_id")
    model = await _models.get_by_id(session, mid)
    label = model.name if model else None
    rows = await _services.list_by_ontology(session, mid)
    allowed: list[str] | None = None
    names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for n in row.tool_names or []:
            name = str(n).strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
    if names:
        allowed = names
    return str(mid), label, allowed


async def handle_streamable(
    request: Request,
    session: AsyncSession,
    *,
    authorization: str | None,
    x_api_key: str | None,
) -> Response:
    await assert_mcp_key(session, authorization, x_api_key)
    bound_id, label, allowed = await resolve_binding(session, extract_ontology_id(request))
    if request.method == "DELETE":
        return Response(status_code=204, headers=_mcp_headers())
    if request.method == "GET":
        return _streamable_get(request)
    return await _streamable_post(request, session, bound_id, label, allowed)


def _streamable_get(request: Request) -> Response:
    accept = (request.headers.get("accept") or "").lower()
    if "text/event-stream" in accept:
        return StreamingResponse(
            _keepalive(), media_type="text/event-stream", headers=_mcp_headers()
        )
    return JSONResponse(
        {
            "server": "KnowMind",
            "transport": "streamable-http",
            "hint": "Cursor 请使用 type: http，对本 URL POST initialize。可用 ?ontology_id= 绑定本体。",
        },
        headers=_mcp_headers(),
    )


async def _streamable_post(request, session, bound_id, label, allowed) -> Response:
    raw = await request.body()
    if not raw.strip():
        return Response(status_code=202, headers=_mcp_headers())
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
            status_code=400,
            headers=_mcp_headers(),
        )
    replies = await _rpc_replies(session, payload, bound_id, label, allowed)
    if not replies:
        return Response(status_code=202, headers=_mcp_headers())
    body: Any = replies if isinstance(payload, list) else replies[0]
    accept = (request.headers.get("accept") or "").lower()
    wants_sse = "application/json" not in accept and "text/event-stream" in accept
    if wants_sse:
        data = json.dumps(body, ensure_ascii=False)
        return StreamingResponse(
            _one_message_event(data), media_type="text/event-stream", headers=_mcp_headers()
        )
    return JSONResponse(body, headers=_mcp_headers())


async def _rpc_replies(session, payload, bound_id, label, allowed) -> list[dict[str, Any]]:
    messages = payload if isinstance(payload, list) else [payload]
    replies: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        reply = await handle_rpc(
            session,
            message,
            caller="mcp",
            ontology_model_id=bound_id,
            allowed_tools=allowed,
            ontology_label=label,
        )
        if reply is not None:
            replies.append(reply)
    return replies


async def _one_message_event(data: str):
    yield f"event: message\ndata: {data}\n\n"


def _mcp_headers() -> dict[str, str]:
    return {
        "mcp-session-id": uuid.uuid4().hex,
        "mcp-protocol-version": "2025-03-26",
    }


async def _keepalive():
    yield ": connected\n\n"
    while True:
        await asyncio.sleep(20)
        yield ": ping\n\n"
