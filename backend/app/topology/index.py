"""In-memory ontology index for topology grounding (P1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from app.topology.normalize import normalize_alias

NAME_LIKE_PROPERTIES = {
    "姓名",
    "名称",
    "name",
    "full_name",
    "工号",
    "编码",
    "标题",
    "接口名称",
    "故障编码",
}

FUZZY_THRESHOLD = 0.82
CANDIDATE_LIMIT = 5


@dataclass(frozen=True)
class IndexedClass:
    id: str
    label: str
    local_name: str | None = None
    parent_class_id: str | None = None
    description: str | None = None
    instance_count: int = 0


@dataclass(frozen=True)
class IndexedRelation:
    property_label: str
    object_id: str
    object_label: str


@dataclass
class IndexedInstance:
    id: str
    class_id: str
    class_label: str
    label: str
    local_name: str | None = None
    aliases: list[str] = field(default_factory=list)
    data_values: dict[str, str] = field(default_factory=dict)
    relations: list[IndexedRelation] = field(default_factory=list)


@dataclass(frozen=True)
class MatchCandidate:
    instance_id: str
    label: str
    score: float
    matched_by: str


@dataclass(frozen=True)
class MatchResult:
    instance_id: str | None
    label: str | None
    matched_by: str
    score: float
    candidates: list[MatchCandidate] = field(default_factory=list)

    @property
    def grounded(self) -> bool:
        return self.instance_id is not None and self.matched_by != "unmatched"


class OntologyIndex:
    """Alias maps: exact label / local_name / normalized alias → instance ids."""

    def __init__(
        self,
        *,
        schema_id: str,
        schema_version: int | None,
        classes: list[IndexedClass],
        instances: list[IndexedInstance],
    ) -> None:
        self.schema_id = schema_id
        self.schema_version = schema_version
        self.classes = {c.id: c for c in classes}
        self.instances = {i.id: i for i in instances}
        self._by_class: dict[str, list[IndexedInstance]] = {}
        self._exact: dict[str, list[str]] = {}
        self._normalized: dict[str, list[str]] = {}
        self._build_maps()

    def _add(self, mapping: dict[str, list[str]], key: str, instance_id: str) -> None:
        if not key:
            return
        bucket = mapping.setdefault(key, [])
        if instance_id not in bucket:
            bucket.append(instance_id)

    def _build_maps(self) -> None:
        for inst in self.instances.values():
            self._by_class.setdefault(inst.class_id, []).append(inst)
            self._add(self._exact, inst.label, inst.id)
            if inst.local_name:
                self._add(self._exact, inst.local_name, inst.id)
            self._add(self._normalized, normalize_alias(inst.label), inst.id)
            self._add(self._normalized, normalize_alias(inst.local_name), inst.id)
            for alias in inst.aliases:
                self._add(self._exact, alias, inst.id)
                self._add(self._normalized, normalize_alias(alias), inst.id)
            for prop, value in inst.data_values.items():
                if prop in NAME_LIKE_PROPERTIES or normalize_alias(prop) in {
                    normalize_alias(x) for x in NAME_LIKE_PROPERTIES
                }:
                    self._add(self._exact, value, inst.id)
                    self._add(self._normalized, normalize_alias(value), inst.id)

    def instances_for_class(self, class_id: str) -> list[IndexedInstance]:
        return list(self._by_class.get(class_id, []))

    def instances_for_classes(self, class_ids: set[str]) -> list[IndexedInstance]:
        out: list[IndexedInstance] = []
        for cid in class_ids:
            out.extend(self._by_class.get(cid, []))
        return out

    def lookup(
        self,
        query: str,
        *,
        class_ids: set[str] | None = None,
        fuzzy_threshold: float = FUZZY_THRESHOLD,
        candidate_limit: int = CANDIDATE_LIMIT,
    ) -> MatchResult:
        """Resolve a document mention onto an existing instance.

        Cascade: uuid → exact label/local_name/alias → normalized → fuzzy → unmatched.
        When class_ids is set, only those classes are eligible (type-scoped grounding).
        """
        q = (query or "").strip()
        if not q:
            return MatchResult(None, None, "unmatched", 0.0, [])

        allowed = class_ids
        if q in self.instances:
            inst = self.instances[q]
            if allowed is None or inst.class_id in allowed:
                return MatchResult(inst.id, inst.label, "exact", 1.0, [])

        exact_ids = self._filter_ids(self._exact.get(q, []), allowed)
        if exact_ids:
            inst = self.instances[exact_ids[0]]
            extras = self._candidates(exact_ids[1:], "exact", 1.0, candidate_limit)
            return MatchResult(inst.id, inst.label, "exact", 1.0, extras)

        norm = normalize_alias(q)
        norm_ids = self._filter_ids(self._normalized.get(norm, []), allowed)
        if norm_ids:
            inst = self.instances[norm_ids[0]]
            extras = self._candidates(norm_ids[1:], "normalized", 0.95, candidate_limit)
            return MatchResult(inst.id, inst.label, "normalized", 0.95, extras)

        pool = (
            self.instances_for_classes(allowed)
            if allowed is not None
            else list(self.instances.values())
        )
        scored: list[tuple[float, IndexedInstance]] = []
        for inst in pool:
            keys = [inst.label, inst.local_name, *inst.aliases, *inst.data_values.values()]
            best = 0.0
            for key in keys:
                nk = normalize_alias(key)
                if not nk:
                    continue
                best = max(best, SequenceMatcher(None, norm, nk).ratio())
            if best >= fuzzy_threshold:
                scored.append((best, inst))
        scored.sort(key=lambda x: (-x[0], x[1].label))
        if not scored:
            near = self._near_misses(norm, pool, candidate_limit)
            return MatchResult(None, None, "unmatched", 0.0, near)

        top_score, top = scored[0]
        extras = [
            MatchCandidate(i.id, i.label, s, "fuzzy")
            for s, i in scored[1:candidate_limit]
        ]
        return MatchResult(top.id, top.label, "fuzzy", round(top_score, 4), extras)

    def _filter_ids(self, ids: list[str], allowed: set[str] | None) -> list[str]:
        if allowed is None:
            return list(ids)
        return [i for i in ids if self.instances[i].class_id in allowed]

    def _candidates(
        self, ids: list[str], matched_by: str, score: float, limit: int
    ) -> list[MatchCandidate]:
        out: list[MatchCandidate] = []
        for iid in ids[:limit]:
            inst = self.instances[iid]
            out.append(MatchCandidate(inst.id, inst.label, score, matched_by))
        return out

    def _near_misses(
        self, norm: str, pool: list[IndexedInstance], limit: int
    ) -> list[MatchCandidate]:
        scored: list[tuple[float, IndexedInstance]] = []
        for inst in pool:
            nk = normalize_alias(inst.label)
            if not nk:
                continue
            scored.append((SequenceMatcher(None, norm, nk).ratio(), inst))
        scored.sort(key=lambda x: -x[0])
        return [
            MatchCandidate(i.id, i.label, round(s, 4), "unmatched")
            for s, i in scored[:limit]
            if s > 0
        ]
