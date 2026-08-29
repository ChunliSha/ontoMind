"""Unified evidence DTO returned by KnowledgeService."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EvidenceTriple(BaseModel):
    subject_id: str
    subject_label: str
    predicate: str
    object_id: str | None = None
    object_label: str | None = None
    object_value: str | None = None


class Evidence(BaseModel):
    id: str
    kind: Literal["instance", "schema", "class", "relation", "triple"] = "instance"
    entity_id: str | None = None
    label: str
    class_label: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    triples: list[EvidenceTriple] = Field(default_factory=list)
    source_ref: dict[str, Any] | None = None


def number_evidences(items: list[Evidence], *, start: int = 1) -> list[Evidence]:
    out: list[Evidence] = []
    for i, ev in enumerate(items, start=start):
        data = ev.model_dump()
        data["id"] = f"E{i}"
        out.append(Evidence.model_validate(data))
    return out


def _evidence_payload_size(ev: Evidence) -> int:
    props = {k: v for k, v in (ev.properties or {}).items() if k != "score"}
    return len(props) + len(ev.triples or [])


def merge_evidences(items: list[Evidence]) -> list[Evidence]:
    """Keep one row per (kind, entity, label); merge later tools' attributes onto search hits."""
    order: list[tuple] = []
    by_key: dict[tuple, Evidence] = {}
    for ev in items:
        key = (ev.kind, ev.entity_id or "", ev.label)
        prev = by_key.get(key)
        if prev is None:
            by_key[key] = ev
            order.append(key)
            continue
        props = {k: v for k, v in (prev.properties or {}).items() if k != "score"}
        props.update({k: v for k, v in (ev.properties or {}).items() if k != "score"})
        triples = list(prev.triples or [])
        seen = {(t.predicate, t.object_id, t.object_value) for t in triples}
        for t in ev.triples or []:
            sig = (t.predicate, t.object_id, t.object_value)
            if sig in seen:
                continue
            triples.append(t)
            seen.add(sig)
        base = ev if _evidence_payload_size(ev) >= _evidence_payload_size(prev) else prev
        by_key[key] = base.model_copy(
            update={
                "properties": props,
                "triples": triples,
                "source_ref": ev.source_ref or prev.source_ref,
            }
        )
    return [by_key[k] for k in order]
