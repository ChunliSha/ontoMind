#!/usr/bin/env python3
"""Populate the power-grid ontology from sample documents.

Extraction follows the semantica.semantic_extract LLM pipeline:

    FileIngestor → NamedEntityRecognizer → RelationExtractor
    → TripletExtractor → RDFExporter, then merge with the existing TBox.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef, XSD

try:
    from semantica.export import RDFExporter
except ModuleNotFoundError:
    from semantica.export.rdf_exporter import RDFExporter
from semantica.ingest import FileIngestor, OntologyIngestor
from semantica.semantic_extract import (
    NamedEntityRecognizer,
    RelationExtractor,
    TripletExtractor,
)
from semantica.semantic_extract.providers import create_provider
from semantica.semantic_extract.types import Entity, Relation, Triplet
from semantica.utils.exceptions import ProcessingError

HERE = Path(__file__).resolve().parent
DEFAULT_SCHEMA = HERE / "power_grid_defect_maintenance_ontology.ttl"
DEFAULT_OUTPUT = HERE / "power_grid_defect_maintenance_populated.ttl"
NS = Namespace("http://ontomind.example.org/power-grid#")


def _local(uri: str) -> str:
    return uri.split("#")[-1].split("/")[-1]


def load_ontology_types(schema_path: Path) -> Dict[str, Any]:
    ingested = OntologyIngestor().ingest_ontology(schema_path, format="turtle")
    payload = ingested.data

    classes: Dict[str, str] = {}
    for item in payload.get("classes", []):
        local = _local(item["uri"])
        classes[local] = item.get("label") or local

    object_props: Dict[str, str] = {}
    data_props: Dict[str, str] = {}
    for item in payload.get("properties", []):
        local = _local(item["uri"])
        label = item.get("label") or local
        if item.get("type") == "data":
            data_props[local] = label
        else:
            object_props[local] = label

    return {
        "uri": payload.get("uri") or str(NS).rstrip("#"),
        "classes": classes,
        "object_props": object_props,
        "data_props": data_props,
    }


def type_hints(mapping: Dict[str, str]) -> List[str]:
    """Pass both local names and Chinese labels so the LLM can ground on the schema."""
    hints: List[str] = []
    for local, label in mapping.items():
        hints.append(f"{local} ({label})" if label != local else local)
    return hints


def build_alias_index(mapping: Dict[str, str]) -> Dict[str, str]:
    index: Dict[str, str] = {}
    for local, label in mapping.items():
        for key in (local, label, local.replace("_", ""), label.replace(" ", "")):
            index[key.lower()] = local
    return index


def normalize_term(raw: str, index: Dict[str, str]) -> Optional[str]:
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


def file_text(doc: Any) -> str:
    if hasattr(doc, "text"):
        return doc.text
    if isinstance(doc, dict):
        return str(doc.get("text") or doc.get("content") or "")
    return str(doc)


def ingest_documents(docs_dir: Path) -> Tuple[List[Any], List[str]]:
    docs = FileIngestor().ingest_directory(
        str(docs_dir),
        recursive=True,
        extensions=["md"],
        pattern="样例文档*",
    )
    docs = sorted(docs, key=lambda d: getattr(d, "name", str(d)))
    texts = [file_text(d) for d in docs]
    if not any(texts):
        raise FileNotFoundError(f"No sample markdown documents ingested from {docs_dir}")
    return docs, texts


def llm_connection(
    provider: str,
    llm_model: Optional[str],
    api_key: Optional[str],
    base_url: Optional[str],
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {"provider": provider}
    if llm_model:
        kwargs["llm_model"] = llm_model
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    return kwargs


def ensure_llm_provider(
    provider: str,
    llm_model: Optional[str],
    api_key: Optional[str],
    base_url: Optional[str],
) -> None:
    try:
        kwargs: Dict[str, Any] = {}
        if llm_model:
            kwargs["model"] = llm_model
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        llm = create_provider(provider, **kwargs)
    except Exception as exc:
        raise ProcessingError(
            f"无法创建 LLM provider '{provider}': {exc}"
        ) from exc
    if not llm.is_available():
        env_key = f"{provider.upper()}_API_KEY"
        raise ProcessingError(
            f"LLM provider '{provider}' 不可用。请安装 openai/instructor，并设置 {env_key} 与可选的 OPENAI_BASE_URL。"
        )


def extract(
    texts: List[str],
    ontology: Dict[str, Any],
    provider: str,
    llm_model: Optional[str],
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Tuple[List[List[Entity]], List[List[Relation]], List[Triplet], List[str]]:
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
        for text, ents in zip(texts, entities)
    ]

    tri = TripletExtractor(
        method="llm",
        include_provenance=True,
        triplet_types=triplet_types,
        **llm_kwargs,
    )
    triplets: List[Triplet] = []
    triplet_source_texts: List[str] = []
    for text, ents, rels in zip(texts, entities, relations):
        doc_triplets = tri.validate_triplets(tri.extract_triplets(text, ents, rels))
        triplets.extend(doc_triplets)
        triplet_source_texts.extend([text] * len(doc_triplets))
    return entities, relations, triplets, triplet_source_texts


def entity_mention(entity: Any) -> str:
    if isinstance(entity, Entity):
        return entity.text
    return str(entity)


def entity_label(entity: Any) -> str:
    if isinstance(entity, Entity):
        return entity.label
    return ""


def map_instances(
    entities: Iterable[Iterable[Entity]],
    ontology: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    class_index = build_alias_index(ontology["classes"])
    instances: Dict[str, Dict[str, Any]] = {}
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
            current = instances.get(key)
            if current is None:
                instances[key] = {
                    "id": key,
                    "iri": iri,
                    "text": text,
                    "type": str(NS[class_local]),
                    "class_local": class_local,
                    "confidence": getattr(ent, "confidence", 1.0),
                }
    return instances


def resolve_instance(text: str, instances: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
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
    """Require data-property values to be attested by the source document (anti-hallucination)."""
    raw = str(value or "").strip()
    if not raw or not text:
        return False
    if raw in text:
        return True
    norm_v = normalize_for_grounding(raw)
    norm_t = normalize_for_grounding(text)
    if norm_v and norm_v in norm_t:
        return True
    # 编码/日期：若值中连续数字片段都能在原文中找到，视为可溯源
    digit_runs = re.findall(r"\d{2,}", raw)
    if digit_runs and all(run in text or run in norm_t for run in digit_runs):
        # 同时要求去掉分隔符后的主体不太短，避免单靠年份误匹配
        compact = re.sub(r"[\s\-_/.:：]", "", raw)
        if len(compact) >= 4 and normalize_for_grounding(compact) in norm_t:
            return True
        if len(digit_runs) >= 2 and all(run in text for run in digit_runs):
            return True
    return False


def map_graph(
    entities: List[List[Entity]],
    relations: List[List[Relation]],
    triplets: List[Triplet],
    ontology: Dict[str, Any],
    texts: Optional[List[str]] = None,
    triplet_source_texts: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], List[Tuple[URIRef, URIRef, Literal]]]:
    instances = map_instances(entities, ontology)
    object_index = build_alias_index(ontology["object_props"])
    data_index = build_alias_index(ontology["data_props"])
    relationships: List[Dict[str, str]] = []
    literals: List[Tuple[URIRef, URIRef, Literal]] = []
    seen_rel = set()
    dropped_ungrounded = 0
    corpus = "\n".join(t for t in (texts or []) if t)

    def add_object_link(subject_text: str, predicate: str, object_text: str) -> None:
        pred = normalize_term(predicate, object_index)
        if not pred:
            return
        src = resolve_instance(subject_text, instances)
        dst = resolve_instance(object_text, instances)
        if not src or not dst:
            return
        triple = (src["id"], str(NS[pred]), dst["id"])
        if triple in seen_rel:
            return
        seen_rel.add(triple)
        relationships.append(
            {"source_id": triple[0], "target_id": triple[2], "type": triple[1]}
        )

    def add_data_link(subject_text: str, predicate: str, value: str, source_text: str) -> None:
        nonlocal dropped_ungrounded
        pred = normalize_term(predicate, data_index)
        src = resolve_instance(subject_text, instances)
        if not pred or not src or not value:
            return
        # 数据属性值必须能在来源文档中溯源，禁止模型臆造
        grounded = is_value_grounded_in_text(value, source_text) or (
            not source_text and is_value_grounded_in_text(value, corpus)
        )
        if not grounded:
            dropped_ungrounded += 1
            return
        datatype = XSD.date if pred.lower().endswith("date") else XSD.string
        literals.append((src["iri"], NS[pred], Literal(value, datatype=datatype)))

    for doc_relations in relations:
        for rel in doc_relations:
            add_object_link(entity_mention(rel.subject), rel.predicate, entity_mention(rel.object))

    if triplet_source_texts is not None and len(triplet_source_texts) == len(triplets):
        paired = zip(triplets, triplet_source_texts)
    else:
        paired = ((t, corpus) for t in triplets)

    for triplet, src_text in paired:
        if normalize_term(triplet.predicate, object_index):
            add_object_link(triplet.subject, triplet.predicate, triplet.object)
        elif normalize_term(triplet.predicate, data_index):
            add_data_link(triplet.subject, triplet.predicate, triplet.object, src_text)

    graph_data = {
        "entities": [
            {
                "id": inst["id"],
                "text": inst["text"],
                "type": inst["type"],
                "confidence": inst["confidence"],
            }
            for inst in instances.values()
        ],
        "relationships": relationships,
        "dropped_ungrounded_literals": dropped_ungrounded,
    }
    return graph_data, literals



def merge_and_export(
    schema_path: Path,
    output_path: Path,
    graph_data: Dict[str, Any],
    literals: List[Tuple[URIRef, URIRef, Literal]],
) -> None:
    exporter = RDFExporter()
    abox_ttl = exporter.export_to_rdf(graph_data, format="turtle")

    merged = Graph()
    merged.parse(schema_path, format="turtle")
    merged.parse(data=abox_ttl, format="turtle")
    merged.bind("", NS)
    for inst in graph_data["entities"]:
        iri = URIRef(inst["id"])
        merged.add((iri, RDFS.label, Literal(inst["text"], lang="zh")))
    for triple in literals:
        merged.add(triple)
    merged.serialize(destination=str(output_path), format="turtle")


def print_summary(
    docs: List[Any],
    entities: List[List[Entity]],
    relations: List[List[Relation]],
    triplets: List[Triplet],
    graph_data: Dict[str, Any],
    literals: Optional[List[Tuple[URIRef, URIRef, Literal]]] = None,
) -> None:
    for doc, ents, rels in zip(docs, entities, relations):
        name = getattr(doc, "name", str(doc))
        print(f"{name}: {len(ents)} 个实体, {len(rels)} 条关系")
        for ent in ents:
            print(f"  - {entity_mention(ent)} ({entity_label(ent)})")
    print(f"\n三元组: {len(triplets)}")
    print(f"对齐后实例: {len(graph_data['entities'])}")
    print(f"对齐后对象属性: {len(graph_data['relationships'])}")
    if literals is not None:
        print(f"对齐后数据属性(已原文接地): {len(literals)}")
    dropped = graph_data.get("dropped_ungrounded_literals", 0)
    if dropped:
        print(f"丢弃未在原文出现的数据属性值: {dropped}")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="用 semantic_extract LLM 流水线填充电力缺陷检修本体")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--docs", type=Path, default=HERE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--provider", default=os.getenv("SEMANTICA_LLM_PROVIDER", "openai"))
    parser.add_argument(
        "--llm-model",
        default=os.getenv("SEMANTICA_LLM_MODEL", "DeepSeek-V4-Flash"),
    )
    parser.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY"))
    parser.add_argument(
        "--base-url",
        default=os.getenv("OPENAI_BASE_URL") or os.getenv("SEMANTICA_LLM_BASE_URL"),
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    ontology = load_ontology_types(args.schema)
    print("本体约束")
    print(f"  类: {', '.join(ontology['classes'])}")
    print(f"  对象属性: {', '.join(ontology['object_props'])}")
    print(f"  数据属性: {', '.join(ontology['data_props'])}")
    print()

    docs, texts = ingest_documents(args.docs)
    try:
        ensure_llm_provider(args.provider, args.llm_model, args.api_key, args.base_url)
        entities, relations, triplets, triplet_sources = extract(
            texts,
            ontology,
            args.provider,
            args.llm_model,
            api_key=args.api_key,
            base_url=args.base_url,
        )
    except ProcessingError as exc:
        print(f"抽取失败: {exc}", file=sys.stderr)
        return 1
    graph_data, literals = map_graph(
        entities,
        relations,
        triplets,
        ontology,
        texts=texts,
        triplet_source_texts=triplet_sources or None,
    )
    if not graph_data["entities"]:
        print("抽取失败: LLM 未抽出可对齐到本体的实例，未覆盖输出文件。", file=sys.stderr)
        return 1
    merge_and_export(args.schema, args.output, graph_data, literals)
    print_summary(docs, entities, relations, triplets, graph_data, literals)
    print(f"\n已写出完整本体: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
