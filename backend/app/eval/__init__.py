"""Golden-set metrics for knowledge QA traces (no live LLM required)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

GOLDEN_PATH = Path(__file__).with_name("golden_set.json")


def load_golden_set() -> list[dict[str, Any]]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def score_trace(item: dict[str, Any], trace: dict[str, Any]) -> dict[str, Any]:
    """Score one planned/executed QA trace against a golden item."""
    intent_ok = (trace.get("intent") or "") == item.get("intent")
    tools_used = [t.get("tool") or t.get("name") for t in (trace.get("tool_trace") or [])]
    must = list(item.get("must_tools") or [])
    tool_ok = True
    for m in must:
        aliases = {m}
        if m == "expand_hops":
            aliases.add("expand_neighbors")
        if m == "expand_neighbors":
            aliases.add("expand_hops")
        if not (aliases & set(tools_used)):
            tool_ok = False
            break
    evidences = trace.get("evidences") or []
    empty = len(evidences) == 0
    empty_ok = bool(item.get("empty_ok"))
    honest = True
    answer = trace.get("answer") or ""
    if item.get("require_honest_empty"):
        honest = empty and ("未找到" in answer or "没有" in answer or "无关" in answer)
    citation_cover = 0.0
    if evidences:
        cited = sum(1 for e in evidences if f"[{e.get('id')}]" in answer or (e.get("id") and e["id"] in answer))
        citation_cover = cited / len(evidences)
    labels = [str(x) for x in (item.get("entity_labels") or [])]
    label_hit = all(any(lb in (e.get("label") or "") for e in evidences) for lb in labels) if labels and evidences else (not labels)
    passed = intent_ok and tool_ok and honest and (empty_ok or not empty)
    return {
        "id": item.get("id"),
        "passed": passed,
        "intent_ok": intent_ok,
        "tool_ok": tool_ok,
        "honest_empty": honest,
        "citation_cover": citation_cover,
        "label_hit": label_hit,
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
