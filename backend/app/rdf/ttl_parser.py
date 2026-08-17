"""Transactional TTL import (§9.2)."""

from __future__ import annotations

from dataclasses import dataclass

from rdflib import OWL, RDF, RDFS, Graph, URIRef
from rdflib.term import Literal

from app.core.exceptions import AppError, ErrorCode
from app.rdf.ttl_builder import label_to_local_name


@dataclass
class ParsedClass:
    label: str
    local_name: str
    parent_local_name: str | None = None
    description: str | None = None


@dataclass
class ParsedProperty:
    label: str
    local_name: str
    kind: str
    domain_local_name: str
    datatype: str | None = None
    range_local_name: str | None = None


def parse_ttl(ttl_text: str) -> Graph:
    g = Graph()
    try:
        g.parse(data=ttl_text, format="turtle")
    except Exception as exc:  # noqa: BLE001
        raise AppError(
            ErrorCode.SCHEMA_003,
            message=f"TTL 文件解析失败，请检查语法（{exc})",
        ) from exc
    return g


def _label_of(g: Graph, node: URIRef) -> str:
    for _, _, o in g.triples((node, RDFS.label, None)):
        if isinstance(o, Literal):
            return str(o)
    # fallback to local part of IRI
    s = str(node)
    if "#" in s:
        return s.rsplit("#", 1)[-1]
    return s.rsplit("/", 1)[-1]


def _local_of(node: URIRef) -> str:
    s = str(node)
    if "#" in s:
        return s.rsplit("#", 1)[-1]
    return s.rsplit("/", 1)[-1]


def extract_entities(g: Graph) -> tuple[list[ParsedClass], list[ParsedProperty]]:
    classes: list[ParsedClass] = []
    for s in g.subjects(RDF.type, OWL.Class):
        if not isinstance(s, URIRef):
            continue
        label = _label_of(g, s)
        local = _local_of(s) or label_to_local_name(label)
        parent = None
        for _, _, o in g.triples((s, RDFS.subClassOf, None)):
            if isinstance(o, URIRef):
                parent = _local_of(o)
                break
        desc = None
        for _, _, o in g.triples((s, RDFS.comment, None)):
            desc = str(o)
            break
        classes.append(
            ParsedClass(label=label, local_name=local, parent_local_name=parent, description=desc)
        )

    properties: list[ParsedProperty] = []
    for kind, rdf_type in (("data", OWL.DatatypeProperty), ("object", OWL.ObjectProperty)):
        for s in g.subjects(RDF.type, rdf_type):
            if not isinstance(s, URIRef):
                continue
            label = _label_of(g, s)
            local = _local_of(s) or label_to_local_name(label)
            domain = None
            for _, _, o in g.triples((s, RDFS.domain, None)):
                if isinstance(o, URIRef):
                    domain = _local_of(o)
                    break
            if not domain:
                continue
            datatype = None
            range_ln = None
            for _, _, o in g.triples((s, RDFS.range, None)):
                if isinstance(o, URIRef):
                    if kind == "data":
                        datatype = f"xsd:{_local_of(o)}"
                    else:
                        range_ln = _local_of(o)
                    break
            properties.append(
                ParsedProperty(
                    label=label,
                    local_name=local,
                    kind=kind,
                    domain_local_name=domain,
                    datatype=datatype or ("xsd:string" if kind == "data" else None),
                    range_local_name=range_ln,
                )
            )
    return classes, properties
