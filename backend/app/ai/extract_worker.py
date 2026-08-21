"""Child-process target for instance extraction. Keep this module free of the task runner."""

from __future__ import annotations

from typing import Any

from multiprocessing.queues import Queue


def extract_worker(
    result_queue: Queue,
    texts: list[str],
    snapshot_dump: dict[str, Any],
    kwargs: dict[str, Any],
) -> None:
    try:
        from app.ai.base import SchemaSnapshot
        from app.ai.populate_ontology_pipeline import extract_instances_sync

        snap = SchemaSnapshot.model_validate(snapshot_dump)
        result = extract_instances_sync(texts, snap, **kwargs)
        result_queue.put(("ok", result.model_dump()))
    except Exception as exc:  # noqa: BLE001
        result_queue.put(("err", f"{type(exc).__name__}: {exc}"))
