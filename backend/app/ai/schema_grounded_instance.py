"""Schema-grounded unstructured instance extraction (legacy / fallback).

Product instance extraction now uses semantica via
`app.ai.populate_ontology_pipeline` (adapted from extract/populate_ontology.py).

This module remains for unit tests of the previous weighted-confidence helpers
and as a non-semantica reference implementation.
"""

from __future__ import annotations

import difflib
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field

from app.ai.base import (
    ExtractedDataValue,
    ExtractedInstance,
    ExtractedRelation,
    InstanceExtractionResult,
    SchemaSnapshot,
)
from app.ai.prompts.instance_grounded import (
    INSTANCE_NER_SYSTEM,
    INSTANCE_RELATION_SYSTEM,
    INSTANCE_TRIPLET_SYSTEM,
)

logger = logging.getLogger(__name__)

ChatFn = Callable[..., Awaitable[str]]

_MAX_CHARS = 12000
_CHUNK_OVERLAP = 800


class _EntityHit(BaseModel):
    text: str
    label: str
    confidence: float = 0.9


class _RelationHit(BaseModel):
    subject: str
    predicate: str
    object: str
    confidence: float = 0.9


class _TripletHit(BaseModel):
    subject: str
    predicate: str
    object: str
    confidence: float = 0.9


class _EntitiesPayload(BaseModel):
    entities: list[_EntityHit] = Field(default_factory=list)


class _RelationsPayload(BaseModel):
    relations: list[_RelationHit] = Field(default_factory=list)


class _TripletsPayload(BaseModel):
    triplets: list[_TripletHit] = Field(default_factory=list)


def _type_hints(pairs: list[tuple[str, str | None]]) -> list[str]:
    hints: list[str] = []
    for label, local in pairs:
        if local and local != label:
            hints.append(f"{local} ({label})")
        else:
            hints.append(label)
    return hints


def _build_alias_index(pairs: list[tuple[str, str | None]]) -> dict[str, str]:
    """Map any alias → canonical schema label (Chinese/business label used by persistence)."""
    index: dict[str, str] = {}
    for label, local in pairs:
        for key in (label, local or "", label.replace(" ", ""), (local or "").replace("_", "")):
            if key:
                index[key.lower()] = label
    return index


def _normalize_term(raw: str, index: dict[str, str]) -> str | None:
    if not raw:
        return None
    text = str(raw).strip().strip("<>").split("/")[-1].split("#")[-1]
    candidates = [text]
    if "(" in text and ")" in text:
        candidates.append(text.split("(")[0].strip())
        candidates.append(text[text.find("(") + 1 : text.rfind(")")].strip())
    for cand in candidates:
        hit = index.get(cand.lower()) or index.get(re.sub(r"[\s_]+", "", cand.lower()))
        if hit:
            return hit
    return None


def _as_unit_confidence(raw: float | None) -> float:
    """Normalize model confidence to [0, 1]."""
    if raw is None:
        return 0.0
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if v > 1.0:
        v = v / 100.0
    return max(0.0, min(1.0, v))


def _expand_type_candidates(entity_types: list[str]) -> list[str]:
    """Expand `Transformer (变压器)` into full / local / zh variants for matching."""
    out: list[str] = []
    seen: set[str] = set()
    for t in entity_types:
        parts = [t]
        if "(" in t and ")" in t:
            parts.append(t.split("(")[0].strip())
            parts.append(t[t.find("(") + 1 : t.rfind(")")].strip())
        for p in parts:
            key = p.strip()
            if key and key.lower() not in seen:
                seen.add(key.lower())
                out.append(key)
    return out


def type_similarity(text: str, candidates: list[str]) -> float:
    """Max similarity of text vs type candidates (exact / substring / fuzzy).

    Aligned with Semantica's string/fuzzy path (no embedding dependency).
    """
    if not text or not candidates:
        return 0.0
    needle = text.strip().lower()
    if not needle:
        return 0.0

    expanded = _expand_type_candidates(candidates)
    best = 0.0
    for cand in expanded:
        c = cand.strip().lower()
        if not c:
            continue
        if needle == c:
            return 1.0
        # "Transformer" vs "Transformer (变压器)" already covered via expansion;
        # still score full-form containment.
        if needle in c or c in needle:
            ratio = min(len(needle), len(c)) / max(len(needle), len(c))
            best = max(best, 0.9 * ratio + 0.1)
        fuzzy = difflib.SequenceMatcher(None, needle, c).ratio()
        best = max(best, fuzzy)
    return float(best)


def calculate_weighted_confidence(
    *,
    model_confidence: float,
    item_label: str,
    item_text: str | None,
    entity_types: list[str] | None,
    weight_method: float = 0.5,
    weight_similarity: float = 0.5,
) -> float:
    """final = 0.5×model + 0.5×max(label_sim, text↔type_sim); skip reweight if no types."""
    model = _as_unit_confidence(model_confidence)
    if not entity_types:
        return model

    label_sim = type_similarity(item_label, entity_types)
    content_sim = type_similarity(item_text or "", entity_types) if item_text else 0.0
    best_sim = max(label_sim, content_sim)

    total = weight_method + weight_similarity
    if total <= 0:
        return model
    w_m = weight_method / total
    w_s = weight_similarity / total
    return max(0.0, min(1.0, w_m * model + w_s * best_sim))


_ENTITY_CONFIDENCE_THRESHOLD = 0.7


def rescore_entities(
    entities: list[_EntityHit],
    entity_types: list[str] | None,
    *,
    threshold: float = _ENTITY_CONFIDENCE_THRESHOLD,
) -> list[_EntityHit]:
    """Re-score with type similarity when entity_types configured; filter by threshold."""
    scored: list[_EntityHit] = []
    for e in entities:
        text = (e.text or "").strip()
        if not text:
            continue
        final = calculate_weighted_confidence(
            model_confidence=e.confidence,
            item_label=e.label,
            item_text=text,
            entity_types=entity_types,
        )
        if final < threshold:
            continue
        scored.append(_EntityHit(text=text, label=e.label, confidence=final))
    return scored


def _normalize_for_grounding(text: str) -> str:
    s = str(text).strip().lower()
    s = (
        s.replace("年", "-")
        .replace("月", "-")
        .replace("日", "")
        .replace("／", "/")
        .replace("–", "-")
        .replace("—", "-")
    )
    return re.sub(r"\s+", "", s)


def is_value_grounded_in_text(value: str, text: str) -> bool:
    """Data-property values must be attested by the source document."""
    raw = str(value or "").strip()
    if not raw or not text:
        return False
    if raw in text:
        return True
    norm_v = _normalize_for_grounding(raw)
    norm_t = _normalize_for_grounding(text)
    if norm_v and norm_v in norm_t:
        return True
    digit_runs = re.findall(r"\d{2,}", raw)
    if digit_runs and all(run in text or run in norm_t for run in digit_runs):
        compact = re.sub(r"[\s\-_/.:：]", "", raw)
        if len(compact) >= 4 and _normalize_for_grounding(compact) in norm_t:
            return True
        if len(digit_runs) >= 2 and all(run in text for run in digit_runs):
            return True
    return False


def _chunk_text(text: str, max_chars: int = _MAX_CHARS, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks


def _parse_json_object(raw: str) -> dict[str, Any]:
    import json

    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.M).strip()
    if text and not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("JSON root must be object")
    return data


def _schema_indexes(snapshot: SchemaSnapshot) -> dict[str, Any]:
    class_pairs: list[tuple[str, str | None]] = []
    object_pairs: list[tuple[str, str | None]] = []
    data_pairs: list[tuple[str, str | None]] = []
    # domain label → props
    class_props: dict[str, list] = {}
    for cls in snapshot.classes:
        local = getattr(cls, "local_name", None)
        class_pairs.append((cls.label, local))
        class_props[cls.label] = cls.properties
        for p in cls.properties:
            plocal = getattr(p, "local_name", None)
            if p.kind == "object":
                object_pairs.append((p.label, plocal))
            else:
                data_pairs.append((p.label, plocal))
    return {
        "class_hints": _type_hints(class_pairs),
        "object_hints": _type_hints(object_pairs),
        "data_hints": _type_hints(data_pairs),
        "class_index": _build_alias_index(class_pairs),
        "object_index": _build_alias_index(object_pairs),
        "data_index": _build_alias_index(data_pairs),
        "class_props": class_props,
    }


async def _chat_json(chat: ChatFn, system: str, user: str) -> dict[str, Any]:
    raw = await chat(system, user, timeout=180.0)
    return _parse_json_object(raw)


async def _extract_entities_chunk(
    chat: ChatFn, chunk: str, class_hints: list[str]
) -> list[_EntityHit]:
    user = (
        f"允许的本体类：{class_hints}\n\n"
        f"文档片段：\n{chunk}"
    )
    try:
        data = await _chat_json(chat, INSTANCE_NER_SYSTEM, user)
        payload = _EntitiesPayload.model_validate(data)
        raw = [e for e in payload.entities if (e.text or "").strip()]
        # entity_types = Schema 类提示；有则加权重打分后再按 0.7 过滤
        return rescore_entities(raw, class_hints or None)
    except Exception as exc:  # noqa: BLE001
        logger.warning("NER chunk failed: %s", exc)
        return []


async def _extract_relations(
    chat: ChatFn,
    text: str,
    entities: list[_EntityHit],
    object_hints: list[str],
) -> list[_RelationHit]:
    if not entities or not object_hints:
        return []
    ent_str = ", ".join(f"{e.text} ({e.label})" for e in entities[:80])
    user = (
        f"允许的对象属性：{object_hints}\n"
        f"已识别实体：{ent_str}\n\n"
        f"文档：\n{text[:_MAX_CHARS]}"
    )
    try:
        data = await _chat_json(chat, INSTANCE_RELATION_SYSTEM, user)
        payload = _RelationsPayload.model_validate(data)
        return [r for r in payload.relations if r.confidence >= 0.6]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Relation extraction failed: %s", exc)
        return []


async def _extract_triplets(
    chat: ChatFn,
    text: str,
    entities: list[_EntityHit],
    relations: list[_RelationHit],
    object_hints: list[str],
    data_hints: list[str],
) -> list[_TripletHit]:
    predicates = object_hints + data_hints
    if not predicates:
        return []
    ent_str = ", ".join(f"{e.text} ({e.label})" for e in entities[:80])
    rel_str = "; ".join(
        f"{r.subject}-[{r.predicate}]->{r.object}" for r in relations[:40]
    )
    user = (
        f"允许的谓词（对象属性+数据属性）：{predicates}\n"
        f"已识别实体：{ent_str}\n"
        f"已识别关系：{rel_str}\n\n"
        f"文档：\n{text[:_MAX_CHARS]}\n\n"
        "提醒：数据属性的 object 必须是文档原文中的字面量。"
    )
    try:
        data = await _chat_json(chat, INSTANCE_TRIPLET_SYSTEM, user)
        payload = _TripletsPayload.model_validate(data)
        return [t for t in payload.triplets if t.confidence >= 0.5]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Triplet extraction failed: %s", exc)
        return []


def _slug(text: str) -> str:
    """Align with extract/populate_ontology.slug — stable instance identity key."""
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", str(text).strip())
    return cleaned.strip("_").lower() or "unnamed"


def _instance_merge_key(class_label: str, label: str) -> tuple[str, str]:
    return (class_label, _slug(label))


def _resolve_mention(needle: str, mentions: dict[str, _EntityHit]) -> _EntityHit | None:
    n = needle.strip()
    if not n:
        return None
    if n in mentions:
        return mentions[n]
    for text, ent in mentions.items():
        if n in text or text in n:
            return ent
    return None


def _map_to_instances(
    entities: list[_EntityHit],
    relations: list[_RelationHit],
    triplets: list[_TripletHit],
    indexes: dict[str, Any],
    source_text: str,
) -> list[ExtractedInstance]:
    class_index: dict[str, str] = indexes["class_index"]
    object_index: dict[str, str] = indexes["object_index"]
    data_index: dict[str, str] = indexes["data_index"]

    # mention text → entity (class-normalized); instances keyed like extract mint_iri
    mentions: dict[str, _EntityHit] = {}
    instances: dict[tuple[str, str], ExtractedInstance] = {}

    for ent in entities:
        class_label = _normalize_term(ent.label, class_index)
        if not class_label:
            continue
        text = ent.text.strip()
        if not text:
            continue
        unit = _as_unit_confidence(ent.confidence)
        mentions[text] = _EntityHit(text=text, label=class_label, confidence=unit)
        key = _instance_merge_key(class_label, text)
        prev = instances.get(key)
        if prev is None:
            instances[key] = ExtractedInstance(
                class_label=class_label,
                label=text,
                local_name=_slug(text),
                confidence=round(unit * 100, 2),
                data_values=[],
                relations=[],
            )
        elif (unit * 100) > (prev.confidence or 0):
            prev.confidence = round(unit * 100, 2)

    def ensure_instance(mention: str, fallback_class: str | None = None) -> ExtractedInstance | None:
        hit = _resolve_mention(mention, mentions)
        text = (hit.text if hit else mention).strip()
        if not text:
            return None
        class_label = hit.label if hit else fallback_class
        if not class_label or class_label not in set(class_index.values()):
            return None
        key = _instance_merge_key(class_label, text)
        if key in instances:
            return instances[key]
        unit = _as_unit_confidence(hit.confidence if hit else 0.8)
        instances[key] = ExtractedInstance(
            class_label=class_label,
            label=text,
            local_name=_slug(text),
            confidence=round(unit * 100, 2),
            data_values=[],
            relations=[],
        )
        return instances[key]

    def add_object(subj: str, pred: str, obj: str) -> None:
        predicate = _normalize_term(pred, object_index)
        if not predicate:
            return
        src = ensure_instance(subj)
        dst = ensure_instance(obj)
        if not src or not dst:
            return
        if any(
            r.property_label == predicate and r.target_instance_label == dst.label
            for r in src.relations
        ):
            return
        src.relations.append(
            ExtractedRelation(property_label=predicate, target_instance_label=dst.label)
        )

    def add_data(subj: str, pred: str, value: str) -> None:
        predicate = _normalize_term(pred, data_index)
        src = ensure_instance(subj)
        if not predicate or not src or not value:
            return
        if not is_value_grounded_in_text(value, source_text):
            logger.info("drop ungrounded data value %s=%r", predicate, value)
            return
        if any(d.property_label == predicate and d.value == value for d in src.data_values):
            return
        src.data_values.append(ExtractedDataValue(property_label=predicate, value=value))

    for rel in relations:
        add_object(rel.subject, rel.predicate, rel.object)

    for tri in triplets:
        if _normalize_term(tri.predicate, object_index):
            add_object(tri.subject, tri.predicate, tri.object)
        elif _normalize_term(tri.predicate, data_index):
            add_data(tri.subject, tri.predicate, tri.object)

    return list(instances.values())


async def extract_instances_schema_grounded(
    texts: list[str],
    schema_snapshot: SchemaSnapshot,
    chat: ChatFn,
) -> InstanceExtractionResult:
    """Run NER → Relation → Triplet → grounded map for one or more texts."""
    indexes = _schema_indexes(schema_snapshot)
    if not indexes["class_hints"]:
        return InstanceExtractionResult(instances=[])

    all_instances: list[ExtractedInstance] = []
    # Merge by (class_label, label) across texts
    merged: dict[tuple[str, str], ExtractedInstance] = {}

    for text in texts:
        usable = (text or "").strip()
        if not usable:
            continue
        entities: list[_EntityHit] = []
        for chunk in _chunk_text(usable):
            entities.extend(await _extract_entities_chunk(chat, chunk, indexes["class_hints"]))

        # de-dupe entities by text
        uniq: dict[str, _EntityHit] = {}
        for e in entities:
            prev = uniq.get(e.text)
            if not prev or e.confidence > prev.confidence:
                uniq[e.text] = e
        entities = list(uniq.values())

        relations = await _extract_relations(
            chat, usable, entities, indexes["object_hints"]
        )
        triplets = await _extract_triplets(
            chat,
            usable,
            entities,
            relations,
            indexes["object_hints"],
            indexes["data_hints"],
        )
        mapped = _map_to_instances(entities, relations, triplets, indexes, usable)
        for inst in mapped:
            key = _instance_merge_key(inst.class_label, inst.label)
            existing = merged.get(key)
            if not existing:
                merged[key] = inst
                continue
            # keep higher confidence
            if (inst.confidence or 0) > (existing.confidence or 0):
                existing.confidence = inst.confidence
            # merge props/relations
            seen_dv = {(d.property_label, d.value) for d in existing.data_values}
            for d in inst.data_values:
                if (d.property_label, d.value) not in seen_dv:
                    existing.data_values.append(d)
            seen_rel = {
                (r.property_label, r.target_instance_label) for r in existing.relations
            }
            for r in inst.relations:
                if (r.property_label, r.target_instance_label) not in seen_rel:
                    existing.relations.append(r)

    all_instances = list(merged.values())
    return InstanceExtractionResult(instances=all_instances)
