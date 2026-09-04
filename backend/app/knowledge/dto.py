"""DTO helpers for KnowledgeService."""

from __future__ import annotations

from app.knowledge.evidence import Evidence
from app.knowledge.search_rank import score_hit
from app.models.instance import OntologyInstance
from app.schemas.knowledge import (
    KnowledgeClassRead,
    KnowledgeInstanceHit,
    KnowledgePropertyRead,
)
from app.services._utils import uid


def class_read(cls) -> KnowledgeClassRead:
    return KnowledgeClassRead(
        id=str(cls.id),
        label=cls.label,
        local_name=cls.local_name,
        description=cls.description,
        parent_class_id=uid(cls.parent_class_id),
    )


def property_read(sl, prop) -> KnowledgePropertyRead:
    domain = sl.classes.get(prop.domain_class_id)
    rng = sl.classes.get(prop.range_class_id) if prop.range_class_id else None
    return KnowledgePropertyRead(
        id=str(prop.id),
        label=prop.label,
        local_name=prop.local_name,
        kind=prop.kind,
        datatype=prop.datatype,
        domain_class_id=str(prop.domain_class_id),
        domain_class_label=domain.label if domain else None,
        range_class_id=uid(prop.range_class_id),
        range_class_label=rng.label if rng else None,
        required=bool(prop.required),
        multi=bool(prop.multi),
    )


def score_search_rows(
    sl, rows, needle: str
) -> list[tuple[float, OntologyInstance]]:
    scored: list[tuple[float, OntologyInstance]] = []
    for inst in rows:
        cls = sl.classes.get(inst.class_id)
        data_values = {}
        for data_val in inst.data_values or []:
            prop = sl.properties.get(data_val.property_id)
            if prop:
                data_values[prop.label] = data_val.value
        score = score_hit(
            needle,
            label=inst.label,
            local_name=inst.local_name,
            class_label=cls.label if cls else None,
            data_values=data_values,
        )
        if not (needle or "").strip():
            score = 0.5
        scored.append((score, inst))
    scored.sort(key=_hit_sort_key)
    return scored


def _hit_sort_key(item: tuple[float, OntologyInstance]) -> tuple[float, str]:
    return (-item[0], item[1].label)


def hits_from_scored(
    sl, scored: list[tuple[float, OntologyInstance]], cap: int
) -> tuple[list[KnowledgeInstanceHit], list[Evidence]]:
    hits: list[KnowledgeInstanceHit] = []
    evidences: list[Evidence] = []
    for score, inst in scored[:cap]:
        cls = sl.classes.get(inst.class_id)
        hits.append(
            KnowledgeInstanceHit(
                id=str(inst.id),
                label=inst.label,
                class_id=str(inst.class_id),
                class_label=cls.label if cls else None,
                local_name=inst.local_name,
                score=round(score, 4),
                schema_id=str(inst.schema_id),
            )
        )
        evidences.append(
            Evidence(
                id="",
                kind="instance",
                entity_id=str(inst.id),
                label=inst.label,
                class_label=cls.label if cls else None,
                properties={"score": round(score, 4)},
                source_ref=inst.source_ref,
            )
        )
    return hits, evidences
