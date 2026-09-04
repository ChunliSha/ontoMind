"""TTL builder using rdflib (§9.1).

Local-name rule:
1. If label/local_name is ASCII identifier-like ([A-Za-z_][A-Za-z0-9_]*), use as-is.
2. Else convert Chinese via pypinyin (join without tone, Capitalize each syllable for classes).
3. If still empty/invalid, use `c_` + uuid hex (8 chars).
Result must be stable for the same input label.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from rdflib import OWL, RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef

try:
    from pypinyin import Style, lazy_pinyin
except ImportError:  # pragma: no cover
    lazy_pinyin = None  # type: ignore[assignment]
    Style = None  # type: ignore[assignment]

_ASCII_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SAFE_RE = re.compile(r"[^A-Za-z0-9_]+")


@dataclass
class ClassSpec:
    label: str
    local_name: str | None = None
    parent_local_name: str | None = None
    description: str | None = None


@dataclass
class PropertySpec:
    label: str
    kind: str  # data | object
    domain_local_name: str
    local_name: str | None = None
    datatype: str | None = None
    range_local_name: str | None = None


@dataclass
class InstanceDataValueSpec:
    property_local_name: str
    value: str
    datatype: str | None = None


@dataclass
class InstanceRelationSpec:
    property_local_name: str
    object_key: str  # same key used for subject instances


@dataclass
class InstanceSpec:
    """ABox individual. `key` is stable within one export (used for object links)."""

    key: str
    class_local_name: str
    label: str
    local_name: str | None = None
    data_values: list[InstanceDataValueSpec] | None = None
    relations: list[InstanceRelationSpec] | None = None


def label_to_local_name(label: str, *, existing: set[str] | None = None) -> str:
    """Deterministic Chinese/ASCII label → safe IRI local name."""
    existing = existing or set()
    raw = (label or "").strip()
    if not raw:
        name = f"c_{uuid.uuid5(uuid.NAMESPACE_URL, 'empty').hex[:8]}"
    elif _ASCII_RE.match(raw):
        name = raw
    else:
        if lazy_pinyin is not None:
            parts = lazy_pinyin(raw, style=Style.NORMAL)
            name = "".join(p.capitalize() if i == 0 else p for i, p in enumerate(parts) if p)
            name = _SAFE_RE.sub("", name)
            if name and name[0].isdigit():
                name = f"n_{name}"
        else:
            name = ""
        if not name or not _ASCII_RE.match(name):
            name = f"c_{uuid.uuid5(uuid.NAMESPACE_URL, raw).hex[:8]}"

    base = name
    i = 2
    while name in existing:
        name = f"{base}_{i}"
        i += 1
    return name


def resolve_local_name(
    label: str, local_name: str | None, *, existing: set[str] | None = None
) -> str:
    if local_name and _ASCII_RE.match(local_name.strip()):
        name = local_name.strip()
        existing = existing or set()
        if name not in existing:
            return name
        return label_to_local_name(label, existing=existing)
    return label_to_local_name(label, existing=existing)


def build_ttl(
    *,
    base_iri: str = "http://example.com/ontomind/schema#",
    classes: list[ClassSpec],
    properties: list[PropertySpec],
    instances: list[InstanceSpec] | None = None,
) -> str:
    graph, namespace = _new_ontology_graph(base_iri)
    used: set[str] = set()
    class_ln = _register_class_names(classes, used)
    _add_class_triples(graph, namespace, classes, class_ln)
    prop_ln = _add_property_triples(graph, namespace, properties, class_ln, used)
    if instances:
        _add_instance_triples(graph, namespace, instances, class_ln, prop_ln, used)
    return graph.serialize(format="turtle")


def _new_ontology_graph(base_iri: str):
    graph = Graph()
    namespace = Namespace(base_iri)
    graph.bind("om", namespace)
    graph.bind("owl", OWL)
    graph.bind("rdfs", RDFS)
    graph.bind("xsd", XSD)
    graph.add((URIRef(base_iri.rstrip("#")), RDF.type, OWL.Ontology))
    return graph, namespace


def _register_class_names(classes: list[ClassSpec], used: set[str]) -> dict[str, str]:
    class_ln: dict[str, str] = {}
    for cls in classes:
        local = resolve_local_name(cls.label, cls.local_name, existing=used)
        used.add(local)
        class_ln[cls.label] = local
        if cls.local_name:
            class_ln[cls.local_name] = local
    return class_ln


def _add_class_triples(graph, namespace, classes: list[ClassSpec], class_ln: dict[str, str]) -> None:
    for cls in classes:
        local = class_ln[cls.label]
        node = namespace[local]
        graph.add((node, RDF.type, OWL.Class))
        graph.add((node, RDFS.label, Literal(cls.label, lang="zh")))
        if cls.description:
            graph.add((node, RDFS.comment, Literal(cls.description, lang="zh")))
        parent = cls.parent_local_name
        if parent:
            parent_ln = class_ln.get(parent, parent)
            graph.add((node, RDFS.subClassOf, namespace[parent_ln]))


def _xsd_range(datatype: str | None):
    xsd_map = {
        "string": XSD.string,
        "int": XSD.int,
        "integer": XSD.integer,
        "dateTime": XSD.dateTime,
        "date": XSD.date,
        "decimal": XSD.decimal,
        "boolean": XSD.boolean,
    }
    key = (datatype or "xsd:string").replace("xsd:", "")
    return xsd_map.get(key, XSD.string)


def _add_property_triples(graph, namespace, properties, class_ln, used: set[str]) -> dict[str, str]:
    prop_ln: dict[str, str] = {}
    for prop in properties:
        local = resolve_local_name(prop.label, prop.local_name, existing=used)
        used.add(local)
        prop_ln[prop.label] = local
        if prop.local_name:
            prop_ln[prop.local_name] = local
        node = namespace[local]
        if prop.kind == "object":
            graph.add((node, RDF.type, OWL.ObjectProperty))
            if prop.range_local_name:
                range_ln = class_ln.get(prop.range_local_name, prop.range_local_name)
                graph.add((node, RDFS.range, namespace[range_ln]))
        else:
            graph.add((node, RDF.type, OWL.DatatypeProperty))
            graph.add((node, RDFS.range, _xsd_range(prop.datatype)))
        graph.add((node, RDFS.label, Literal(prop.label, lang="zh")))
        domain_ln = class_ln.get(prop.domain_local_name, prop.domain_local_name)
        graph.add((node, RDFS.domain, namespace[domain_ln]))
    return prop_ln


def _add_instance_triples(graph, namespace, instances, class_ln, prop_ln, used: set[str]) -> None:
    xsd_map = {
        "string": XSD.string,
        "xsd:string": XSD.string,
        "int": XSD.int,
        "integer": XSD.integer,
        "xsd:integer": XSD.integer,
        "dateTime": XSD.dateTime,
        "xsd:dateTime": XSD.dateTime,
        "date": XSD.date,
        "xsd:date": XSD.date,
        "decimal": XSD.decimal,
        "xsd:decimal": XSD.decimal,
        "boolean": XSD.boolean,
        "xsd:boolean": XSD.boolean,
    }
    inst_nodes = _mint_instance_nodes(graph, namespace, instances, class_ln, used)
    for inst in instances:
        node = inst_nodes.get(inst.key)
        if node is None:
            continue
        _add_instance_values(graph, namespace, inst, node, inst_nodes, prop_ln, xsd_map)


def _mint_instance_nodes(graph, namespace, instances, class_ln, used: set[str]):
    inst_nodes = {}
    for inst in instances:
        class_ln_name = class_ln.get(inst.class_local_name, inst.class_local_name)
        slug = (inst.local_name or "").strip()
        if not slug or not _ASCII_RE.match(slug):
            slug = label_to_local_name(inst.label)
        iri_ln = f"{class_ln_name}_{slug}"
        base_iri_ln = iri_ln
        seq = 2
        while iri_ln in used:
            iri_ln = f"{base_iri_ln}_{seq}"
            seq += 1
        used.add(iri_ln)
        node = namespace[iri_ln]
        inst_nodes[inst.key] = node
        graph.add((node, RDF.type, namespace[class_ln_name]))
        graph.add((node, RDFS.label, Literal(inst.label, lang="zh")))
    return inst_nodes


def _add_instance_values(graph, namespace, inst, node, inst_nodes, prop_ln, xsd_map) -> None:
    for data_val in inst.data_values or []:
        prop_local = prop_ln.get(data_val.property_local_name, data_val.property_local_name)
        datatype = xsd_map.get((data_val.datatype or "xsd:string"), XSD.string)
        is_date = datatype == XSD.date or (data_val.property_local_name or "").lower().endswith("date")
        if is_date:
            graph.add((node, namespace[prop_local], Literal(data_val.value, datatype=XSD.date)))
        else:
            graph.add((node, namespace[prop_local], Literal(data_val.value, datatype=datatype)))
    for rel in inst.relations or []:
        prop_local = prop_ln.get(rel.property_local_name, rel.property_local_name)
        obj = inst_nodes.get(rel.object_key)
        if obj is not None:
            graph.add((node, namespace[prop_local], obj))
