"""KnowMind Knowledge MCP server (stdio + optional SSE on MCP_PORT)."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Any

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.mcp.protocol import handle_rpc

logger = logging.getLogger("ontomind.mcp")


async def _read_stdio_message() -> dict[str, Any] | None:
    """Read one MCP stdio message (Content-Length framing, or a single JSON line)."""
    loop = asyncio.get_event_loop()
    first = await loop.run_in_executor(None, sys.stdin.readline)
    if first == "":
        return None
    if first.lstrip().startswith("{"):
        return json.loads(first)
    headers: dict[str, str] = {}
    line = first
    while True:
        if line == "":
            return None
        stripped = line.strip()
        if stripped == "":
            break
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        line = await loop.run_in_executor(None, sys.stdin.readline)
    n = int(headers.get("content-length") or "0")
    if n <= 0:
        return None
    body = await loop.run_in_executor(None, lambda: sys.stdin.read(n))
    return json.loads(body)


def _write(msg: dict[str, Any]) -> None:
    payload = json.dumps(msg, ensure_ascii=False)
    raw = payload.encode("utf-8")
    sys.stdout.write(f"Content-Length: {len(raw)}\r\n\r\n")
    sys.stdout.write(payload)
    sys.stdout.flush()


async def _stdio_loop() -> None:
    while True:
        try:
            message = await _read_stdio_message()
        except json.JSONDecodeError:
            _write({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        if message is None:
            break
        if not isinstance(message, dict):
            continue
        reply = await _dispatch_stdio(message)
        if reply is not None:
            _write(reply)


async def _dispatch_stdio(message: dict) -> dict | None:
    async with AsyncSessionLocal() as session:
        try:
            reply = await handle_rpc(session, message, caller="mcp")
            await session.commit()
            return reply
        except Exception:  # noqa: BLE001
            logger.exception("MCP request failed")
            await session.rollback()
            _write_internal_error(message)
            return None


def _write_internal_error(message: dict) -> None:
    if message.get("id") is None:
        return
    _write(
        {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {"code": -32603, "message": "Internal error"},
        }
    )


async def _run_sse() -> None:
    import uvicorn

    from app.mcp.http_app import create_mcp_http_app

    app = create_mcp_http_app()
    config = uvicorn.Config(
        app,
        host=settings.MCP_BIND_HOST or "127.0.0.1",
        port=int(settings.MCP_PORT),
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="KnowMind Knowledge MCP server")
    parser.add_argument("--sse", action="store_true", help="Serve MCP JSON-RPC over HTTP/SSE (bind 127.0.0.1)")
    parser.add_argument("--stdio", action="store_true", help="Serve MCP over stdio (default)")
    args = parser.parse_args(argv)
    if args.sse:
        asyncio.run(_run_sse())
        return
    try:
        from mcp.server.fastmcp import FastMCP

        from app.mcp.fastmcp_bridge import register_fastmcp

        mcp = FastMCP("KnowMind")
        register_fastmcp(mcp)
        mcp.run(transport="stdio")
        return
    except Exception:  # noqa: BLE001 — fall back to built-in JSON-RPC stdio
        logger.info("mcp SDK FastMCP unavailable, using built-in stdio JSON-RPC")
    asyncio.run(_stdio_loop())


if __name__ == "__main__":
    main()
