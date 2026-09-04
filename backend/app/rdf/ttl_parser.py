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
    return _parse_classes(g), _parse_properties(g)


def _parse_classes(g: Graph) -> list[ParsedClass]:
    classes: list[ParsedClass] = []
    for subj in g.subjects(RDF.type, OWL.Class):
        if not isinstance(subj, URIRef):
            continue
        label = _label_of(g, subj)
        local = _local_of(subj) or label_to_local_name(label)
        parent = _first_local(g, subj, RDFS.subClassOf)
        desc = None
        for _, _, obj in g.triples((subj, RDFS.comment, None)):
            desc = str(obj)
            break
        classes.append(
            ParsedClass(label=label, local_name=local, parent_local_name=parent, description=desc)
        )
    return classes


def _first_local(g: Graph, subj: URIRef, pred) -> str | None:
    for _, _, obj in g.triples((subj, pred, None)):
        if isinstance(obj, URIRef):
            return _local_of(obj)
    return None


def _parse_properties(g: Graph) -> list[ParsedProperty]:
    properties: list[ParsedProperty] = []
    for kind, rdf_type in (("data", OWL.DatatypeProperty), ("object", OWL.ObjectProperty)):
        properties.extend(_parse_properties_of_kind(g, kind, rdf_type))
    return properties


def _parse_properties_of_kind(g: Graph, kind: str, rdf_type) -> list[ParsedProperty]:
    properties: list[ParsedProperty] = []
    for subj in g.subjects(RDF.type, rdf_type):
        item = _parse_one_property(g, subj, kind)
        if item is not None:
            properties.append(item)
    return properties


def _parse_one_property(g: Graph, subj, kind: str) -> ParsedProperty | None:
    if not isinstance(subj, URIRef):
        return None
    label = _label_of(g, subj)
    local = _local_of(subj) or label_to_local_name(label)
    domain = _first_local(g, subj, RDFS.domain)
    if not domain:
        return None
    datatype, range_ln = _range_of(g, subj, kind)
    return ParsedProperty(
        label=label,
        local_name=local,
        kind=kind,
        domain_local_name=domain,
        datatype=datatype or ("xsd:string" if kind == "data" else None),
        range_local_name=range_ln,
    )


def _range_of(g: Graph, subj: URIRef, kind: str) -> tuple[str | None, str | None]:
    for _, _, obj in g.triples((subj, RDFS.range, None)):
        if not isinstance(obj, URIRef):
            continue
        if kind == "data":
            return f"xsd:{_local_of(obj)}", None
        return None, _local_of(obj)
    return None, None
