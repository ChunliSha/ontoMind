"""MCP JSON-RPC initialize / tools/list / unknown tool."""

from __future__ import annotations

import pytest

from app.mcp.protocol import apply_bound_ontology, bind_tool_schemas, handle_rpc, negotiate_protocol_version
from app.mcp.tools import TOOL_SCHEMAS, call_tool


class _DummySession:
    pass


@pytest.mark.asyncio
async def test_initialize_and_list():
    init = await handle_rpc(_DummySession(), {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert init["result"]["serverInfo"]["name"] == "KnowMind"
    listed = await handle_rpc(_DummySession(), {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in listed["result"]["tools"]}
    assert "search_instances" in names
    assert "get_schema" in names
    assert "ask_knowledge" in names
    assert "execute_sparql" not in names
    assert len(TOOL_SCHEMAS) >= 8


@pytest.mark.asyncio
async def test_unknown_tool():
    out = await call_tool(_DummySession(), "execute_sql", {})
    assert out["ok"] is False


@pytest.mark.asyncio
async def test_initialize_negotiates_cursor_protocol():
    init = await handle_rpc(
        _DummySession(),
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "cursor"}},
        },
    )
    assert init["result"]["protocolVersion"] == "2025-03-26"


@pytest.mark.asyncio
async def test_bound_ontology_filters_and_injects():
    mid = "062c8a6b-b717-4868-982d-eb26f6603a08"
    listed = await handle_rpc(
        _DummySession(),
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ontology_model_id=mid,
        allowed_tools=["ask_knowledge"],
        ontology_label="滨江变电站检修 · v2",
    )
    tools = listed["result"]["tools"]
    assert [t["name"] for t in tools] == ["ask_knowledge"]
    required = tools[0]["inputSchema"].get("required") or []
    assert "ontology_model_id" not in required
    note = await handle_rpc(
        _DummySession(),
        {"jsonrpc": "2.0", "id": 3, "method": "notifications/initialized"},
        ontology_model_id=mid,
    )
    assert note is None


def test_apply_bound_ontology():
    mid = "062c8a6b-b717-4868-982d-eb26f6603a08"
    assert apply_bound_ontology({"question": "有哪些员工？"}, mid)["ontology_model_id"] == mid
    assert apply_bound_ontology({"ontology_model_id": "keep"}, mid)["ontology_model_id"] == "keep"


def test_bind_tool_schemas_strips_required():
    mid = "062c8a6b-b717-4868-982d-eb26f6603a08"
    schemas = bind_tool_schemas(ontology_model_id=mid, allowed_tools=["ask_knowledge", "get_schema"])
    names = [t["name"] for t in schemas]
    assert names == ["get_schema", "ask_knowledge"]
    for t in schemas:
        assert "ontology_model_id" not in (t["inputSchema"].get("required") or [])


def test_negotiate_protocol_version():
    assert negotiate_protocol_version("2025-06-18") == "2025-06-18"
    assert negotiate_protocol_version(None) == "2024-11-05"
    assert negotiate_protocol_version("99") == "2025-03-26"
