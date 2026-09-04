"""Restricted SPARQL subset facade → KnowledgeService plans (not a second store)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.exceptions import AppError, ErrorCode
from app.knowledge.limits import clamp_limit

_FORBIDDEN = re.compile(
    r"\b(INSERT|DELETE|UPDATE|DROP|LOAD|CLEAR|CREATE|CONSTRUCT|DESCRIBE|ASK|"
    r"SERVICE|GRAPH|OPTIONAL|UNION|MINUS|BIND|VALUES|FILTER|WITH|COPY|MOVE|"
    r"ADD|SILENT)\b",
    re.IGNORECASE,
)

_SELECT_RE = re.compile(
    r"^\s*SELECT\s+(?P<vars>.+?)\s+WHERE\s*\{(?P<where>.+)\}\s*(?:LIMIT\s+(?P<limit>\d+))?\s*$",
    re.IGNORECASE | re.DOTALL,
)

# ?s :pred ?o   |  <uuid> :pred "lit"  |  ?s rdfs:label "x"
_TRIPLE_RE = re.compile(
    r"""
    (?P<s>\?[A-Za-z_]\w*|<[^>]+>|"[^"]*"|'[^']*')
    \s+
    (?P<p>\?[A-Za-z_]\w*|<[^>]+>|:?[^\s]+)
    \s+
    (?P<o>\?[A-Za-z_]\w*|<[^>]+>|"[^"]*"|'[^']*')
    \s*\.?
    """,
    re.VERBOSE,
)


@dataclass
class SparqlPlan:
    action: Literal["search_instances", "get_instance", "list_relations", "reject"]
    args: dict[str, Any] = field(default_factory=dict)
    limit: int = 20
    raw: str = ""


def parse_sparql_subset(query: str) -> SparqlPlan:
    text, triples, limit = _parse_select(query)
    for triple in triples:
        plan = _plan_from_triple(triple, limit, text)
        if plan is not None:
            return plan
    return _fallback_plan(triples, limit, text)


def _parse_select(query: str) -> tuple[str, list, int]:
    text = (query or "").strip()
    if not text:
        raise AppError(ErrorCode.VALIDATION_ERROR, message="SPARQL 不能为空", field="query")
    if _FORBIDDEN.search(text):
        raise AppError(
            ErrorCode.KNOWLEDGE_002,
            message="仅允许受限 SELECT + WHERE + LIMIT，禁止更新、OPTIONAL、UNION、FILTER 等算子",
        )
    matched = _SELECT_RE.match(text)
    if not matched:
        raise AppError(
            ErrorCode.KNOWLEDGE_002,
            message="无法解析为 SELECT … WHERE { … } LIMIT n 子集",
        )
    where = matched.group("where").strip()
    triples = list(_TRIPLE_RE.finditer(where))
    if not triples:
        raise AppError(ErrorCode.KNOWLEDGE_002, message="WHERE 中未找到三元组")
    if len(triples) > 3:
        raise AppError(ErrorCode.KNOWLEDGE_002, message="WHERE 三元组过多（最多 3 条）")
    limit = clamp_limit(int(matched.group("limit")) if matched.group("limit") else 20)
    return text, triples, limit


def _plan_from_triple(triple, limit: int, text: str) -> SparqlPlan | None:
    pred = _pred_name(triple.group("p"))
    obj = triple.group("o")
    subj = triple.group("s")
    if pred in {"rdfs:label", "label", ":label"} and _is_literal(obj):
        return SparqlPlan(action="search_instances", args={"q": _strip_term(obj)}, limit=limit, raw=text)
    if _is_iri_or_uuid(subj) and pred not in {"?p"} and not pred.startswith("?"):
        iid = _id_from_iri(subj)
        if _is_var(obj) or _is_iri_or_uuid(obj):
            return SparqlPlan(
                action="list_relations",
                args={"instance_id": iid, "property_label": pred.lstrip(":")},
                limit=limit,
                raw=text,
            )
        return SparqlPlan(action="get_instance", args={"instance_id": iid}, limit=limit, raw=text)
    if _is_literal(obj) and not pred.startswith("?"):
        return SparqlPlan(
            action="search_instances",
            args={"q": _strip_term(obj), "class_label": None},
            limit=limit,
            raw=text,
        )
    return None


def _fallback_plan(triples, limit: int, text: str) -> SparqlPlan:
    unbound = all(
        _is_var(item.group("s")) and _is_var(item.group("p")) and _is_var(item.group("o"))
        for item in triples
    )
    if unbound:
        raise AppError(ErrorCode.KNOWLEDGE_002, message="禁止无约束全表扫描")
    first = triples[0]
    if _is_iri_or_uuid(first.group("s")):
        return SparqlPlan(
            action="get_instance",
            args={"instance_id": _id_from_iri(first.group("s"))},
            limit=limit,
            raw=text,
        )
    raise AppError(ErrorCode.KNOWLEDGE_002, message="该 SPARQL 模式不受支持")


def _is_var(term: str) -> bool:
    return term.startswith("?")


def _is_literal(term: str) -> bool:
    return len(term) >= 2 and term[0] in {'"', "'"}


def _is_iri_or_uuid(term: str) -> bool:
    if term.startswith("<") and term.endswith(">"):
        return True
    body = term.strip("<>")
    return bool(re.fullmatch(r"[0-9a-fA-F-]{36}", body))


def _strip_term(term: str) -> str:
    if _is_literal(term):
        return term[1:-1]
    if term.startswith("<") and term.endswith(">"):
        return term[1:-1]
    return term.lstrip(":")


def _pred_name(term: str) -> str:
    t = term.strip()
    if t.startswith("<") and t.endswith(">"):
        iri = t[1:-1]
        if "#" in iri:
            return iri.rsplit("#", 1)[-1]
        return iri.rsplit("/", 1)[-1]
    return t.lstrip(":")


def _id_from_iri(term: str) -> str:
    body = _strip_term(term)
    m = re.search(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", body)
    if not m:
        raise AppError(ErrorCode.KNOWLEDGE_002, message="IRI 中未找到实例 UUID")
    return m.group(0)
