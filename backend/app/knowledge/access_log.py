"""Write knowledge_access_log rows (shared by REST, QA, MCP)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeAccessLog
from app.services._utils import parse_uuid


async def log_access(
    session: AsyncSession,
    *,
    caller: str,
    tool_name: str,
    ontology_model_id: str | uuid.UUID | None = None,
    session_id: str | uuid.UUID | None = None,
    trace_id: str = "",
    plan: dict[str, Any] | None = None,
    request_meta: dict[str, Any] | None = None,
    latency_ms: int = 0,
    empty_hit: bool = False,
    error: str | None = None,
) -> None:
    mid = None
    if ontology_model_id:
        try:
            mid = ontology_model_id if isinstance(ontology_model_id, uuid.UUID) else parse_uuid(str(ontology_model_id))
        except Exception:  # noqa: BLE001 — log should never fail the query
            mid = None
    sid = None
    if session_id:
        try:
            sid = session_id if isinstance(session_id, uuid.UUID) else parse_uuid(str(session_id))
        except Exception:  # noqa: BLE001
            sid = None
    session.add(
        KnowledgeAccessLog(
            caller=caller[:16],
            tool_name=tool_name[:64],
            ontology_model_id=mid,
            session_id=sid,
            trace_id=(trace_id or "")[:64],
            plan=plan,
            request_meta=request_meta,
            latency_ms=int(latency_ms),
            empty_hit=bool(empty_hit),
            error=(error or None),
        )
    )
    await session.flush()
