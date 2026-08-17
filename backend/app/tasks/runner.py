"""In-process asyncio task runner for extraction_task (§7.5)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from decimal import Decimal

from app.db.session import AsyncSessionLocal
from app.models.extraction import ExtractionTask

logger = logging.getLogger(__name__)

# task_id -> asyncio.Task
_running: dict[uuid.UUID, asyncio.Task] = {}


async def update_task_progress(
    task_id: uuid.UUID,
    *,
    status: str | None = None,
    progress: float | None = None,
    output_summary: dict | None = None,
    error_message: str | None = None,
) -> None:
    async with AsyncSessionLocal() as session:
        task = await session.get(ExtractionTask, task_id)
        if not task:
            return
        if status:
            task.status = status
            if status == "running" and task.started_at is None:
                task.started_at = datetime.now(timezone.utc)
            if status in ("succeeded", "failed"):
                task.finished_at = datetime.now(timezone.utc)
        if progress is not None:
            task.progress = Decimal(str(round(progress, 2)))
        if output_summary is not None:
            task.output_summary = output_summary
        if error_message is not None:
            task.error_message = error_message
        await session.commit()


async def _wrap(
    task_id: uuid.UUID,
    coro_factory: Callable[[uuid.UUID], Awaitable[None]],
) -> None:
    try:
        await update_task_progress(task_id, status="running", progress=0)
        await coro_factory(task_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("extraction task %s failed", task_id)
        await update_task_progress(
            task_id,
            status="failed",
            error_message=str(exc),
        )
    finally:
        _running.pop(task_id, None)


def spawn(task_id: uuid.UUID, coro_factory: Callable[[uuid.UUID], Awaitable[None]]) -> None:
    """Fire-and-forget asyncio.create_task."""
    t = asyncio.create_task(_wrap(task_id, coro_factory), name=f"extraction-{task_id}")
    _running[task_id] = t
