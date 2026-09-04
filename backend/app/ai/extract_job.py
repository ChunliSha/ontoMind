"""Cancellable instance extraction in a child process so the LLM call can be killed."""

from __future__ import annotations

import logging
import multiprocessing as mp
import queue
import uuid
from typing import Any

from app.ai.base import InstanceExtractionResult, SchemaSnapshot
from app.ai.extract_worker import extract_worker
from app.tasks.runner import (
    ExtractionCancelled,
    is_cancelled,
    register_extract_process,
    unregister_extract_process,
)

logger = logging.getLogger(__name__)


def _kill(proc: mp.Process) -> None:
    if not proc.is_alive():
        return
    proc.terminate()
    proc.join(timeout=3)
    if proc.is_alive():
        proc.kill()
        proc.join(timeout=2)


def run_extract_cancellable(
    task_id: uuid.UUID,
    texts: list[str],
    snapshot: SchemaSnapshot,
    **llm_kwargs: Any,
) -> InstanceExtractionResult:
    """Run Semantica extraction in a subprocess; terminate it if the task is cancelled."""
    if is_cancelled(task_id):
        raise ExtractionCancelled("用户已终止抽取")

    ctx = mp.get_context("spawn")
    result_queue: mp.Queue = ctx.Queue()
    proc = ctx.Process(
        target=extract_worker,
        args=(result_queue, texts, snapshot.model_dump(), llm_kwargs),
        daemon=True,
        name=f"extract-{task_id}",
    )
    register_extract_process(task_id, proc)
    proc.start()
    try:
        kind, payload = _wait_queue_result(task_id, proc, result_queue)
        if is_cancelled(task_id):
            raise ExtractionCancelled("用户已终止抽取")
        if kind == "err":
            raise RuntimeError(str(payload))
        return InstanceExtractionResult.model_validate(payload)
    finally:
        unregister_extract_process(task_id)
        _cleanup_proc(task_id, proc)


def _wait_queue_result(task_id, proc, result_queue):
    while True:
        if is_cancelled(task_id):
            _kill(proc)
            raise ExtractionCancelled("用户已终止抽取")
        got = _try_queue_get(proc, result_queue)
        if got is not None:
            return got


def _try_queue_get(proc, result_queue):
    try:
        return result_queue.get(timeout=0.4)
    except queue.Empty:
        if proc.is_alive():
            return None
        return _final_queue_get(result_queue)


def _final_queue_get(result_queue):
    try:
        return result_queue.get_nowait()
    except queue.Empty:
        raise RuntimeError("抽取进程异常退出") from None


def _cleanup_proc(task_id, proc) -> None:
    if not proc.is_alive():
        return
    if is_cancelled(task_id):
        _kill(proc)
        return
    proc.join(timeout=2)
    if proc.is_alive():
        _kill(proc)
