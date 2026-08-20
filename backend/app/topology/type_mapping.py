"""Suggest ontology class → topology node-type mapping (P1)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.topology.index import IndexedClass, OntologyIndex
from app.topology.node_types import NodeTypeRegistry, NodeTypeSpec, get_default_registry
from app.topology.normalize import normalize_alias

KEYWORD_HIT = 80
EXACT_HIT = 100
DESC_HIT = 30
COUNT_CAP = 20
ASSIGN_THRESHOLD = 80


@dataclass
class ClassTypeScore:
    class_id: str
    class_label: str
    local_name: str | None
    instance_count: int
    type_key: str
    score: float
    reasons: list[str] = field(default_factory=list)


@dataclass
class TypeMappingSuggestion:
    type_key: str
    class_ids: list[str]
    class_labels: list[str]
    candidates: list[ClassTypeScore]
    instance_count: int


@dataclass
class TypeMappingResult:
    mapping: list[TypeMappingSuggestion]
    unmapped_classes: list[IndexedClass]


def score_class_against_type(cls: IndexedClass, spec: NodeTypeSpec) -> ClassTypeScore:
    reasons: list[str] = []
    score = 0.0
    label_n = normalize_alias(cls.label)
    local_n = normalize_alias(cls.local_name)
    type_n = normalize_alias(spec.type_key)

    if label_n == type_n or (local_n and local_n == type_n):
        score += EXACT_HIT
        reasons.append("exact_label")

    hay_label = f"{cls.label} {cls.local_name or ''}"
    for kw in spec.class_keywords:
        if not kw:
            continue
        if kw in hay_label or normalize_alias(kw) in {label_n, local_n}:
            score += KEYWORD_HIT
            reasons.append(f"keyword:{kw}")
            break
        if cls.description and kw in cls.description:
            score += DESC_HIT
            reasons.append(f"description:{kw}")
            break

    if cls.instance_count:
        bonus = min(COUNT_CAP, cls.instance_count)
        score += bonus
        reasons.append(f"instances:{cls.instance_count}")

    return ClassTypeScore(
        class_id=cls.id,
        class_label=cls.label,
        local_name=cls.local_name,
        instance_count=cls.instance_count,
        type_key=spec.type_key,
        score=score,
        reasons=reasons,
    )


def suggest_type_mapping(
    index: OntologyIndex,
    registry: NodeTypeRegistry | None = None,
    *,
    threshold: float = ASSIGN_THRESHOLD,
) -> TypeMappingResult:
    """Assign each class to at most one node type (highest score ≥ threshold)."""
    reg = registry or get_default_registry()
    specs = reg.all()
    assigned: dict[str, ClassTypeScore] = {}
    all_scores: list[ClassTypeScore] = []

    for cls in index.classes.values():
        best: ClassTypeScore | None = None
        for spec in specs:
            item = score_class_against_type(cls, spec)
            all_scores.append(item)
            if best is None or item.score > best.score:
                best = item
        if best and best.score >= threshold:
            assigned[cls.id] = best

    mapping: list[TypeMappingSuggestion] = []
    for spec in specs:
        chosen = [s for s in assigned.values() if s.type_key == spec.type_key]
        chosen.sort(key=lambda s: (-s.score, s.class_label))
        type_scores = [s for s in all_scores if s.type_key == spec.type_key]
        type_scores.sort(key=lambda s: (-s.score, s.class_label))
        class_ids = [s.class_id for s in chosen]
        inst_count = sum(len(index.instances_for_class(cid)) for cid in class_ids)
        mapping.append(
            TypeMappingSuggestion(
                type_key=spec.type_key,
                class_ids=class_ids,
                class_labels=[s.class_label for s in chosen],
                candidates=type_scores[:8],
                instance_count=inst_count,
            )
        )

    unmapped = [c for c in index.classes.values() if c.id not in assigned]
    unmapped.sort(key=lambda c: c.label)
    return TypeMappingResult(mapping=mapping, unmapped_classes=unmapped)
