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
) -> str:
    g = Graph()
    om = Namespace(base_iri)
    g.bind("om", om)
    g.bind("owl", OWL)
    g.bind("rdfs", RDFS)
    g.bind("xsd", XSD)

    g.add((URIRef(base_iri.rstrip("#")), RDF.type, OWL.Ontology))

    used: set[str] = set()
    class_ln: dict[str, str] = {}
    for c in classes:
        ln = resolve_local_name(c.label, c.local_name, existing=used)
        used.add(ln)
        class_ln[c.label] = ln
        if c.local_name:
            class_ln[c.local_name] = ln

    for c in classes:
        ln = class_ln[c.label]
        node = om[ln]
        g.add((node, RDF.type, OWL.Class))
        g.add((node, RDFS.label, Literal(c.label, lang="zh")))
        if c.description:
            g.add((node, RDFS.comment, Literal(c.description, lang="zh")))
        parent = c.parent_local_name
        if parent:
            parent_ln = class_ln.get(parent, parent)
            g.add((node, RDFS.subClassOf, om[parent_ln]))

    for p in properties:
        ln = resolve_local_name(p.label, p.local_name, existing=used)
        used.add(ln)
        node = om[ln]
        if p.kind == "object":
            g.add((node, RDF.type, OWL.ObjectProperty))
            if p.range_local_name:
                range_ln = class_ln.get(p.range_local_name, p.range_local_name)
                g.add((node, RDFS.range, om[range_ln]))
        else:
            g.add((node, RDF.type, OWL.DatatypeProperty))
            dt = (p.datatype or "xsd:string").replace("xsd:", "")
            xsd_map = {
                "string": XSD.string,
                "int": XSD.int,
                "integer": XSD.integer,
                "dateTime": XSD.dateTime,
                "decimal": XSD.decimal,
                "boolean": XSD.boolean,
            }
            g.add((node, RDFS.range, xsd_map.get(dt, XSD.string)))
        g.add((node, RDFS.label, Literal(p.label, lang="zh")))
        domain_ln = class_ln.get(p.domain_local_name, p.domain_local_name)
        g.add((node, RDFS.domain, om[domain_ln]))

    return g.serialize(format="turtle")
