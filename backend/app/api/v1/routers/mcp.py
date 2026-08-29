"""MCP HTTP endpoints: protocol + admin (API keys, services)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.mcp.auth import assert_mcp_key
from app.mcp.streamable import handle_streamable
from app.mcp.tools import TOOL_SCHEMAS, call_tool
from app.schemas.mcp_admin import (
    McpApiKeyCreate,
    McpApiKeyCreated,
    McpApiKeyRead,
    McpPublishedTool,
    McpServiceCreate,
    McpServiceRead,
    McpServiceUpdate,
)
from app.services.mcp_admin_service import McpAdminService

router = APIRouter(prefix="/mcp", tags=["mcp"])
admin = McpAdminService()


class ToolCallBody(BaseModel):
    name: str
    arguments: dict = Field(default_factory=dict)


async def _require_mcp_key(
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> None:
    await assert_mcp_key(session, authorization, x_api_key)


async def _streamable(
    request: Request,
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
):
    return await handle_streamable(
        request, session, authorization=authorization, x_api_key=x_api_key
    )


@router.get("/admin/tools", response_model=list[McpPublishedTool])
async def list_published_tools():
    return admin.published_tools()


@router.get("/api-keys", response_model=list[McpApiKeyRead])
async def list_api_keys(session: AsyncSession = Depends(get_session)):
    return await admin.list_keys(session)


@router.post("/api-keys", response_model=McpApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(body: McpApiKeyCreate, session: AsyncSession = Depends(get_session)):
    return await admin.create_key(session, name=body.name)


@router.delete("/api-keys/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(id: str, session: AsyncSession = Depends(get_session)):
    await admin.delete_key(session, id)


@router.get("/services", response_model=list[McpServiceRead])
async def list_services(session: AsyncSession = Depends(get_session)):
    return await admin.list_services(session)


@router.post("/services", response_model=McpServiceRead, status_code=status.HTTP_201_CREATED)
async def create_service(body: McpServiceCreate, session: AsyncSession = Depends(get_session)):
    return await admin.create_service(session, body)


@router.patch("/services/{id}", response_model=McpServiceRead)
async def update_service(id: str, body: McpServiceUpdate, session: AsyncSession = Depends(get_session)):
    return await admin.update_service(session, id, body)


@router.delete("/services/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service(id: str, session: AsyncSession = Depends(get_session)):
    await admin.delete_service(session, id)


@router.get("/tools")
async def list_tools(_: None = Depends(_require_mcp_key)):
    return {"tools": TOOL_SCHEMAS}


@router.post("/tools/call")
async def tools_call(
    body: ToolCallBody,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(_require_mcp_key),
):
    return await call_tool(session, body.name, body.arguments, caller="mcp")


# Cursor `type: "http"` POSTs initialize to the URL. Bind ontology with ?ontology_id=.
router.add_api_route("", _streamable, methods=["GET", "POST", "DELETE"], include_in_schema=True)
router.add_api_route("/", _streamable, methods=["GET", "POST", "DELETE"], include_in_schema=False)
router.add_api_route("/sse", _streamable, methods=["GET", "POST", "DELETE"], include_in_schema=True)
router.add_api_route("/rpc", _streamable, methods=["GET", "POST", "DELETE"], include_in_schema=True)
