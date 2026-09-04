"""Semantica-based instance extraction, adapted from extract/populate_ontology.py.

Pipeline:

    NamedEntityRecognizer → RelationExtractor → TripletExtractor
    → alias normalize → data-value grounding → ExtractedInstance

CLI / file I/O / RDF merge from the reference script are omitted; ontology
constraints come from SchemaSnapshot (DB), and results map to product types.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from rdflib import Literal, Namespace, URIRef, XSD

from app.ai.base import (
    ExtractedDataValue,
    ExtractedInstance,
    ExtractedRelation,
    InstanceExtractionResult,
    SchemaSnapshot,
)

logger = logging.getLogger(__name__)

try:
    from semantica.semantic_extract import (
        NamedEntityRecognizer,
        RelationExtractor,
        TripletExtractor,
    )
    from semantica.semantic_extract.providers import create_provider
    from semantica.semantic_extract.types import Entity, Relation, Triplet
    from semantica.utils.exceptions import ProcessingError
except ImportError as exc:  # pragma: no cover
    NamedEntityRecognizer = None  # type: ignore[misc, assignment]
    RelationExtractor = None  # type: ignore[misc, assignment]
    TripletExtractor = None  # type: ignore[misc, assignment]
    create_provider = None  # type: ignore[misc, assignment]
    Entity = Any  # type: ignore[misc, assignment]
    Relation = Any  # type: ignore[misc, assignment]
    Triplet = Any  # type: ignore[misc, assignment]
    ProcessingError = RuntimeError  # type: ignore[misc, assignment]
    _SEMANTICA_IMPORT_ERROR = exc
else:
    _SEMANTICA_IMPORT_ERROR = None

# Internal IRI minting only (same idea as reference script).
NS = Namespace("http://ontomind.example.org/extract#")


def _require_semantica() -> None:
    if _SEMANTICA_IMPORT_ERROR is not None:
        raise ProcessingError(
            "未安装 semantica，无法使用本体抽取流水线。"
            f" 请 pip install semantica。原始错误: {_SEMANTICA_IMPORT_ERROR}"
        )


def schema_snapshot_to_ontology(snapshot: SchemaSnapshot) -> dict[str, Any]:
    """Build the ontology dict expected by extract/map_graph from SchemaSnapshot.

    Mapping shape matches populate_ontology.load_ontology_types:
      classes / object_props / data_props: local_name → display label
    """
    classes: dict[str, str] = {}
    object_props: dict[str, str] = {}
    data_props: dict[str, str] = {}

    for cls in snapshot.classes:
        local = (cls.local_name or cls.label or "").strip()
        if not local:
            continue
        classes[local] = cls.label or local
        for prop in cls.properties:
            plocal = (prop.local_name or prop.label or "").strip()
            if not plocal:
                continue
            label = prop.label or plocal
            if prop.kind == "data":
                data_props[plocal] = label
            else:
                object_props[plocal] = label

    return {
        "uri": str(NS).rstrip("#"),
        "classes": classes,
        "object_props": object_props,
        "data_props": data_props,
    }


def type_hints(mapping: dict[str, str]) -> list[str]:
    """Pass both local names and Chinese labels so the LLM can ground on the schema."""
    hints: list[str] = []
    for local, label in mapping.items():
        hints.append(f"{local} ({label})" if label != local else local)
    return hints


def build_alias_index(mapping: dict[str, str]) -> dict[str, str]:
    index: dict[str, str] = {}
    for local, label in mapping.items():
        for key in (local, label, local.replace("_", ""), label.replace(" ", "")):
            index[key.lower()] = local
    return index


def normalize_term(raw: str, index: dict[str, str]) -> str | None:
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


def slug(text: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", str(text).strip())
    return cleaned.strip("_") or "unnamed"


def mint_iri(kind: str, text: str) -> URIRef:
    return NS[f"{kind}_{slug(text)}"]


def llm_connection(
    provider: str,
    llm_model: str | None,
    api_key: str | None,
    base_url: str | None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"provider": provider}
    if llm_model:
        kwargs["llm_model"] = llm_model
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    return kwargs


def ensure_llm_provider(
    provider: str,
    llm_model: str | None,
    api_key: str | None,
    base_url: str | None,
) -> None:
    _require_semantica()
    try:
        kwargs: dict[str, Any] = {}
        if llm_model:
            kwargs["model"] = llm_model
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        llm = create_provider(provider, **kwargs)
    except Exception as exc:  # noqa: BLE001
        raise ProcessingError(f"无法创建 LLM provider '{provider}': {exc}") from exc
    if not llm.is_available():
        env_key = f"{provider.upper()}_API_KEY"
        raise ProcessingError(
            f"LLM provider '{provider}' 不可用。请安装 openai/instructor，并设置 {env_key} "
            "与可选的 OPENAI_BASE_URL。"
        )


def extract(
    texts: list[str],
    ontology: dict[str, Any],
    provider: str,
    llm_model: str | None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> tuple[list[list[Any]], list[list[Any]], list[Any], list[str]]:
    """Run NER → Relation → Triplet (same as extract/populate_ontology.extract)."""
    _require_semantica()
    classes = type_hints(ontology["classes"])
    object_props = type_hints(ontology["object_props"])
    triplet_types = object_props + type_hints(ontology["data_props"])
    llm_kwargs = llm_connection(provider, llm_model, api_key, base_url)

    ner = NamedEntityRecognizer(
        methods=["llm"],
        entity_types=classes,
        confidence_threshold=0.7,
        include_standard_types=False,
        **llm_kwargs,
    )
    entities = ner.process_batch(texts)

    rel = RelationExtractor(
        method=["llm"],
        relation_types=object_props,
        confidence_threshold=0.6,
        **llm_kwargs,
    )
    relations = [
        rel.extract_relations(text, entities=ents)
        for text, ents in zip(texts, entities, strict=False)
    ]

    tri = TripletExtractor(
        method="llm",
        include_provenance=True,
        triplet_types=triplet_types,
        **llm_kwargs,
    )
    triplets: list[Any] = []
    triplet_source_texts: list[str] = []
    for text, ents, rels in zip(texts, entities, relations, strict=False):
        doc_triplets = tri.validate_triplets(tri.extract_triplets(text, ents, rels))
        triplets.extend(doc_triplets)
        triplet_source_texts.extend([text] * len(doc_triplets))
    return entities, relations, triplets, triplet_source_texts


def entity_mention(entity: Any) -> str:
    if Entity is not Any and isinstance(entity, Entity):
        return entity.text
    return str(getattr(entity, "text", entity))


def entity_label(entity: Any) -> str:
    if Entity is not Any and isinstance(entity, Entity):
        return entity.label
    return str(getattr(entity, "label", "") or "")


def map_instances(
    entities: Any,
    ontology: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    class_index = build_alias_index(ontology["classes"])
    instances: dict[str, dict[str, Any]] = {}
    for doc_entities in entities:
        for ent in doc_entities:
            class_local = normalize_term(entity_label(ent), class_index)
            if not class_local:
                continue
            text = entity_mention(ent).strip()
            if not text:
                continue
            iri = mint_iri(class_local, text)
            key = str(iri)
            if key not in instances:
                instances[key] = {
                    "id": key,
                    "iri": iri,
                    "text": text,
                    "type": str(NS[class_local]),
                    "class_local": class_local,
                    "confidence": float(getattr(ent, "confidence", 1.0) or 1.0),
                }
    return instances


def resolve_instance(text: str, instances: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    needle = str(text).strip()
    if not needle:
        return None
    for inst in instances.values():
        if inst["text"] == needle or needle in inst["text"] or inst["text"] in needle:
            return inst
    return None


def normalize_for_grounding(text: str) -> str:
    """Normalize text so date/code variants can still be grounded to the source."""
    s = str(text).strip().lower()
    s = (
        s.replace("年", "-")
        .replace("月", "-")
        .replace("日", "")
        .replace("／", "/")
        .replace("–", "-")
        .replace("—", "-")
    )
    s = re.sub(r"\s+", "", s)
    return s


def is_value_grounded_in_text(value: str, text: str) -> bool:
    """Require data-property values to be attested by the source document."""
    raw = str(value or "").strip()
    if not raw or not text:
        return False
    if raw in text:
        return True
    norm_v = normalize_for_grounding(raw)
    norm_t = normalize_for_grounding(text)
    if norm_v and norm_v in norm_t:
        return True
    digit_runs = re.findall(r"\d{2,}", raw)
    if digit_runs and all(run in text or run in norm_t for run in digit_runs):
        compact = re.sub(r"[\s\-_/.:：]", "", raw)
        if len(compact) >= 4 and normalize_for_grounding(compact) in norm_t:
            return True
        if len(digit_runs) >= 2 and all(run in text for run in digit_runs):
            return True
    return False


@dataclass
class _GraphMapper:
    instances: dict
    object_index: dict
    data_index: dict
    corpus: str
    relationships: list[dict[str, str]] = field(default_factory=list)
    literals: list[tuple[URIRef, URIRef, Literal]] = field(default_factory=list)
    seen_rel: set[tuple[str, str, str]] = field(default_factory=set)
    dropped_ungrounded: int = 0

    def add_object_link(self, subject_text: str, predicate: str, object_text: str) -> None:
        pred = normalize_term(predicate, self.object_index)
        if not pred:
            return
        src = resolve_instance(subject_text, self.instances)
        dst = resolve_instance(object_text, self.instances)
        if not src or not dst:
            return
        triple = (src["id"], str(NS[pred]), dst["id"])
        if triple in self.seen_rel:
            return
        self.seen_rel.add(triple)
        self.relationships.append(
            {
                "source_id": triple[0],
                "target_id": triple[2],
                "type": triple[1],
                "pred_local": pred,
            }
        )

    def add_data_link(self, subject_text: str, predicate: str, value: str, source_text: str) -> None:
        pred = normalize_term(predicate, self.data_index)
        src = resolve_instance(subject_text, self.instances)
        if not pred or not src or not value:
            return
        grounded = is_value_grounded_in_text(value, source_text) or (
            not source_text and is_value_grounded_in_text(value, self.corpus)
        )
        if not grounded:
            self.dropped_ungrounded += 1
            return
        datatype = XSD.date if pred.lower().endswith("date") else XSD.string
        self.literals.append((src["iri"], NS[pred], Literal(value, datatype=datatype)))

    def graph_data(self) -> dict[str, Any]:
        return {
            "entities": [
                {
                    "id": inst["id"],
                    "text": inst["text"],
                    "type": inst["type"],
                    "class_local": inst["class_local"],
                    "confidence": inst["confidence"],
                }
                for inst in self.instances.values()
            ],
            "relationships": self.relationships,
            "dropped_ungrounded_literals": self.dropped_ungrounded,
            "_instances": self.instances,
        }


def map_graph(
    entities: list[list[Any]],
    relations: list[list[Any]],
    triplets: list[Any],
    ontology: dict[str, Any],
    texts: list[str] | None = None,
    triplet_source_texts: list[str] | None = None,
) -> tuple[dict[str, Any], list[tuple[URIRef, URIRef, Literal]]]:
    corpus = "\n".join(t for t in (texts or []) if t)
    mapper = _GraphMapper(
        instances=map_instances(entities, ontology),
        object_index=build_alias_index(ontology["object_props"]),
        data_index=build_alias_index(ontology["data_props"]),
        corpus=corpus,
    )
    for doc_relations in relations:
        for rel in doc_relations:
            mapper.add_object_link(
                entity_mention(rel.subject),
                rel.predicate,
                entity_mention(rel.object),
            )
    _map_triplets(mapper, triplets, triplet_source_texts, corpus)
    return mapper.graph_data(), mapper.literals


def _map_triplets(mapper: _GraphMapper, triplets, triplet_source_texts, corpus) -> None:
    if triplet_source_texts is not None and len(triplet_source_texts) == len(triplets):
        paired = zip(triplets, triplet_source_texts, strict=True)
    else:
        paired = ((item, corpus) for item in triplets)
    for triplet, src_text in paired:
        if normalize_term(triplet.predicate, mapper.object_index):
            mapper.add_object_link(triplet.subject, triplet.predicate, triplet.object)
        elif normalize_term(triplet.predicate, mapper.data_index):
            mapper.add_data_link(triplet.subject, triplet.predicate, triplet.object, src_text)


def _uri_local(uri: str | URIRef) -> str:
    s = str(uri)
    return s.split("#")[-1].split("/")[-1]


def _confidence_pct(raw: float | None) -> float:
    """Persist layer expects roughly 0–100."""
    try:
        v = float(raw if raw is not None else 0.8)
    except (TypeError, ValueError):
        v = 0.8
    if v <= 1.0:
        v *= 100.0
    return round(max(0.0, min(100.0, v)), 2)


def graph_to_extracted(
    graph_data: dict[str, Any],
    literals: list[tuple[URIRef, URIRef, Literal]],
    ontology: dict[str, Any],
) -> list[ExtractedInstance]:
    """Convert reference map_graph output → product ExtractedInstance list."""
    by_id = _entities_to_extracted(graph_data, ontology["classes"])
    _apply_object_rels(by_id, graph_data.get("relationships") or [], ontology["object_props"])
    _apply_literals(by_id, literals, ontology["data_props"])
    return list(by_id.values())


def _entities_to_extracted(graph_data: dict[str, Any], class_labels: dict) -> dict[str, ExtractedInstance]:
    by_id: dict[str, ExtractedInstance] = {}
    for ent in graph_data.get("entities") or []:
        class_local = ent.get("class_local") or _uri_local(ent.get("type") or "")
        class_label = class_labels.get(class_local, class_local)
        text = str(ent.get("text") or "").strip()
        if not text or not class_label:
            continue
        by_id[ent["id"]] = ExtractedInstance(
            class_label=class_label,
            label=text,
            local_name=slug(text),
            confidence=_confidence_pct(ent.get("confidence")),
            data_values=[],
            relations=[],
        )
    return by_id


def _apply_object_rels(by_id, relationships, object_labels) -> None:
    for rel in relationships:
        src = by_id.get(rel["source_id"])
        dst = by_id.get(rel["target_id"])
        if not src or not dst:
            continue
        pred_local = rel.get("pred_local") or _uri_local(rel.get("type") or "")
        prop_label = object_labels.get(pred_local, pred_local)
        already = any(
            item.property_label == prop_label and item.target_instance_label == dst.label
            for item in src.relations
        )
        if already:
            continue
        src.relations.append(
            ExtractedRelation(property_label=prop_label, target_instance_label=dst.label)
        )


def _apply_literals(by_id, literals, data_labels) -> None:
    for subj_iri, pred_uri, lit in literals:
        src = by_id.get(str(subj_iri))
        if not src:
            continue
        pred_local = _uri_local(pred_uri)
        prop_label = data_labels.get(pred_local, pred_local)
        value = str(lit)
        already = any(
            item.property_label == prop_label and item.value == value for item in src.data_values
        )
        if already:
            continue
        src.data_values.append(ExtractedDataValue(property_label=prop_label, value=value))


def extract_instances_sync(
    texts: list[str],
    schema_snapshot: SchemaSnapshot,
    *,
    provider: str = "openai",
    llm_model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> InstanceExtractionResult:
    """Synchronous entry used by the async provider (via to_thread)."""
    _require_semantica()
    usable = [t.strip() for t in texts if t and str(t).strip()]
    if not usable:
        return InstanceExtractionResult(instances=[])

    ontology = schema_snapshot_to_ontology(schema_snapshot)
    if not ontology["classes"]:
        return InstanceExtractionResult(instances=[])

    ensure_llm_provider(provider, llm_model, api_key, base_url)
    entities, relations, triplets, triplet_sources = extract(
        usable,
        ontology,
        provider,
        llm_model,
        api_key=api_key,
        base_url=base_url,
    )
    graph_data, literals = map_graph(
        entities,
        relations,
        triplets,
        ontology,
        texts=usable,
        triplet_source_texts=triplet_sources or None,
    )
    dropped = graph_data.get("dropped_ungrounded_literals", 0)
    if dropped:
        logger.info("dropped %s ungrounded data-property values", dropped)

    instances = graph_to_extracted(graph_data, literals, ontology)
    return InstanceExtractionResult(instances=instances)


# ---- helpers still used by extraction_service / tests ----

def instance_merge_key(class_label: str, mention: str) -> tuple[str, str]:
    return (class_label.strip().lower(), slug(mention).lower())
