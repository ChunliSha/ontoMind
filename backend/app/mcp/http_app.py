"""HTTP/SSE MCP JSON-RPC app (bind 127.0.0.1). Optional API key."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.core.exceptions import register_exception_handlers
from app.db.session import AsyncSessionLocal
from app.knowledge.service import KnowledgeService
from app.mcp.auth import assert_mcp_key
from app.mcp.protocol import handle_rpc
from app.mcp.tools import TOOL_SCHEMAS, call_tool


class RpcBody(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str | None = None
    method: str
    params: dict | None = None


class ToolCallBody(BaseModel):
    name: str
    arguments: dict = Field(default_factory=dict)


async def health():
    return {"status": "ok", "server": "KnowMind"}


async def sse_events() -> AsyncIterator[str]:
    yield "event: endpoint\ndata: /messages\n\n"
    while True:
        await asyncio.sleep(15)
        yield "event: ping\ndata: {}\n\n"


async def sse(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
):
    async with AsyncSessionLocal() as session:
        await assert_mcp_key(session, authorization, x_api_key)
        await session.commit()
    return StreamingResponse(sse_events(), media_type="text/event-stream")


async def _rpc_reply(body: RpcBody, authorization: str | None, x_api_key: str | None):
    async with AsyncSessionLocal() as session:
        await assert_mcp_key(session, authorization, x_api_key)
        reply = await handle_rpc(session, body.model_dump(), caller="mcp")
        await session.commit()
    return JSONResponse(reply or {"ok": True})


async def messages(
    body: RpcBody,
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
):
    return await _rpc_reply(body, authorization, x_api_key)


async def rpc(
    body: RpcBody,
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
):
    return await _rpc_reply(body, authorization, x_api_key)


async def list_tools(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
):
    async with AsyncSessionLocal() as session:
        await assert_mcp_key(session, authorization, x_api_key)
        await session.commit()
    return {"tools": TOOL_SCHEMAS}


async def tools_call(
    body: ToolCallBody,
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
):
    async with AsyncSessionLocal() as session:
        await assert_mcp_key(session, authorization, x_api_key)
        out = await call_tool(session, body.name, body.arguments, caller="mcp")
        await session.commit()
    return out


async def access_logs(
    limit: int = 50,
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
):
    svc = KnowledgeService()
    async with AsyncSessionLocal() as session:
        await assert_mcp_key(session, authorization, x_api_key)
        rows = await svc.list_access_logs(session, caller="mcp", limit=limit)
        await session.commit()
    return [row.model_dump() for row in rows]


def create_mcp_http_app() -> FastAPI:
    app = FastAPI(title="KnowMind MCP", version="0.1.0")
    register_exception_handlers(app)
    app.add_api_route("/health", health, methods=["GET"])
    app.add_api_route("/sse", sse, methods=["GET"])
    app.add_api_route("/messages", messages, methods=["POST"])
    app.add_api_route("/rpc", rpc, methods=["POST"])
    app.add_api_route("/tools", list_tools, methods=["GET"])
    app.add_api_route("/tools/call", tools_call, methods=["POST"])
    app.add_api_route("/access-logs", access_logs, methods=["GET"])
    return app
