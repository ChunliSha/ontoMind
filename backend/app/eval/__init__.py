"""Golden-set metrics for knowledge QA traces (no live LLM required)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

GOLDEN_PATH = Path(__file__).with_name("golden_set.json")


def load_golden_set() -> list[dict[str, Any]]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def _tool_ok(must: list[str], tools_used: list[str]) -> bool:
    used = set(tools_used)
    for name in must:
        aliases = {name}
        if name in {"expand_hops", "expand_neighbors"}:
            aliases.update({"expand_hops", "expand_neighbors"})
        if not (aliases & used):
            return False
    return True


def _citation_cover(evidences: list[dict[str, Any]], answer: str) -> float:
    if not evidences:
        return 0.0
    cited = 0
    for evid in evidences:
        evid_id = evid.get("id")
        if f"[{evid_id}]" in answer or (evid_id and evid_id in answer):
            cited += 1
    return cited / len(evidences)


def _honest_empty(item: dict[str, Any], empty: bool, answer: str) -> bool:
    if not item.get("require_honest_empty"):
        return True
    has_phrase = "未找到" in answer or "没有" in answer or "无关" in answer
    return empty and has_phrase


def _label_hit(labels: list[str], evidences: list[dict[str, Any]]) -> bool:
    if not labels:
        return True
    if not evidences:
        return False
    for label in labels:
        if not any(label in (evid.get("label") or "") for evid in evidences):
            return False
    return True


def score_trace(item: dict[str, Any], trace: dict[str, Any]) -> dict[str, Any]:
    """Score one planned/executed QA trace against a golden item."""
    intent_ok = (trace.get("intent") or "") == item.get("intent")
    tools_used = [t.get("tool") or t.get("name") for t in (trace.get("tool_trace") or [])]
    tool_ok = _tool_ok(list(item.get("must_tools") or []), tools_used)
    evidences = trace.get("evidences") or []
    empty = len(evidences) == 0
    answer = trace.get("answer") or ""
    honest = _honest_empty(item, empty, answer)
    labels = [str(x) for x in (item.get("entity_labels") or [])]
    passed = intent_ok and tool_ok and honest and (bool(item.get("empty_ok")) or not empty)
    return {
        "id": item.get("id"),
        "passed": passed,
        "intent_ok": intent_ok,
        "tool_ok": tool_ok,
        "honest_empty": honest,
        "citation_cover": _citation_cover(evidences, answer),
        "label_hit": _label_hit(labels, evidences),
        "empty_hit": empty,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows) or 1
    return {
        "total": len(rows),
        "accuracy": sum(1 for r in rows if r.get("passed")) / n,
        "intent_accuracy": sum(1 for r in rows if r.get("intent_ok")) / n,
        "tool_success": sum(1 for r in rows if r.get("tool_ok")) / n,
        "citation_cover": sum(float(r.get("citation_cover") or 0) for r in rows) / n,
        "empty_hit_rate": sum(1 for r in rows if r.get("empty_hit")) / n,
    }
