"""In-process extraction runner. Heavy jobs run on a dedicated thread/loop
so FastAPI request handling stays responsive.
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing as mp
import threading
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from decimal import Decimal

from app.db.session import (
    clear_worker_sessionmaker,
    create_worker_sessionmaker,
    session_scope,
    set_worker_sessionmaker,
)
from app.models.extraction import ExtractionTask

logger = logging.getLogger(__name__)

CANCEL_MESSAGE = "用户已终止抽取"

_running: dict[uuid.UUID, threading.Thread] = {}
_cancel_events: dict[uuid.UUID, threading.Event] = {}
_extract_procs: dict[uuid.UUID, mp.Process] = {}


class ExtractionCancelled(Exception):
    """Raised when the user stops an in-flight extraction task."""


def cancel_event(task_id: uuid.UUID) -> threading.Event:
    return _cancel_events.setdefault(task_id, threading.Event())


def is_cancelled(task_id: uuid.UUID) -> bool:
    ev = _cancel_events.get(task_id)
    return ev is not None and ev.is_set()


def register_extract_process(task_id: uuid.UUID, proc: mp.Process) -> None:
    _extract_procs[task_id] = proc


def unregister_extract_process(task_id: uuid.UUID) -> None:
    _extract_procs.pop(task_id, None)


def request_cancel(task_id: uuid.UUID) -> None:
    cancel_event(task_id).set()
    proc = _extract_procs.get(task_id)
    if proc is not None and proc.is_alive():
        proc.terminate()
        proc.join(timeout=3)
        if proc.is_alive():
            proc.kill()


def is_alive(task_id: uuid.UUID) -> bool:
    t = _running.get(task_id)
    return t is not None and t.is_alive()


async def update_task_progress(
    task_id: uuid.UUID,
    *,
    status: str | None = None,
    progress: float | None = None,
    output_summary: dict | None = None,
    error_message: str | None = None,
) -> None:
    async with session_scope() as session:
        task = await session.get(ExtractionTask, task_id)
        if not task:
            return
        if task.status in ("succeeded", "failed") and task.finished_at is not None:
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
        await update_task_progress(
            task_id,
            status="running",
            progress=0,
            output_summary={"stage": "正在启动抽取…"},
        )
        if is_cancelled(task_id):
            raise ExtractionCancelled(CANCEL_MESSAGE)
        await coro_factory(task_id)
    except ExtractionCancelled as exc:
        await update_task_progress(
            task_id,
            status="failed",
            error_message=str(exc) or CANCEL_MESSAGE,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("extraction task %s failed", task_id)
        await update_task_progress(
            task_id,
            status="failed",
            error_message=str(exc),
        )
    finally:
        _running.pop(task_id, None)
        _extract_procs.pop(task_id, None)
        _cancel_events.pop(task_id, None)


async def _isolated(task_id: uuid.UUID, coro_factory: Callable[[uuid.UUID], Awaitable[None]]) -> None:
    engine, sm = create_worker_sessionmaker()
    set_worker_sessionmaker(sm)
    try:
        await _wrap(task_id, coro_factory)
    finally:
        clear_worker_sessionmaker()
        await engine.dispose()


def spawn(task_id: uuid.UUID, coro_factory: Callable[[uuid.UUID], Awaitable[None]]) -> None:
    """Run extraction off the API event loop (dedicated thread + engine)."""
    cancel_event(task_id).clear()

    def thread_main() -> None:
        asyncio.run(_isolated(task_id, coro_factory))

    t = threading.Thread(
        target=thread_main,
        name=f"extraction-{task_id}",
        daemon=True,
    )
    _running[task_id] = t
    t.start()
