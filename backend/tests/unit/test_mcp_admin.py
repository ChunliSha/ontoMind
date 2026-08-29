"""MCP admin helpers: key hash and published-tool validation."""

import pytest

from app.core.exceptions import AppError
from app.mcp.auth import hash_mcp_key
from app.mcp.tools import TOOL_SCHEMAS
from app.services.mcp_admin_service import McpAdminService


def test_hash_mcp_key_is_stable():
    a = hash_mcp_key("omk_test")
    b = hash_mcp_key("omk_test")
    assert a == b
    assert len(a) == 64
    assert a != hash_mcp_key("omk_other")


def test_validate_tools_rejects_unknown():
    svc = McpAdminService()
    known = next(t["name"] for t in TOOL_SCHEMAS)
    assert svc._validate_tools([known, known]) == [known]
    with pytest.raises(AppError):
        svc._validate_tools(["not_a_real_tool"])


def test_published_tools_non_empty():
    tools = McpAdminService().published_tools()
    names = {t.name for t in tools}
    assert "search_instances" in names
    assert "get_schema" in names
