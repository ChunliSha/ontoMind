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
        while True:
            if is_cancelled(task_id):
                _kill(proc)
                raise ExtractionCancelled("用户已终止抽取")
            try:
                kind, payload = result_queue.get(timeout=0.4)
                break
            except queue.Empty:
                if proc.is_alive():
                    continue
                try:
                    kind, payload = result_queue.get_nowait()
                    break
                except queue.Empty:
                    raise RuntimeError("抽取进程异常退出") from None
        if is_cancelled(task_id):
            raise ExtractionCancelled("用户已终止抽取")
        if kind == "err":
            raise RuntimeError(str(payload))
        return InstanceExtractionResult.model_validate(payload)
    finally:
        unregister_extract_process(task_id)
        if proc.is_alive():
            if is_cancelled(task_id):
                _kill(proc)
            else:
                proc.join(timeout=2)
                if proc.is_alive():
                    _kill(proc)
