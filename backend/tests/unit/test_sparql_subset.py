"""SPARQL subset facade: only SELECT + WHERE + LIMIT."""

import pytest

from app.core.exceptions import AppError, ErrorCode
from app.knowledge.sparql_subset import parse_sparql_subset


def test_label_search():
    plan = parse_sparql_subset(
        'SELECT ?s WHERE { ?s rdfs:label "1号主变压器" } LIMIT 10'
    )
    assert plan.action == "search_instances"
    assert plan.args["q"] == "1号主变压器"
    assert plan.limit == 10


def test_instance_relation_by_uuid():
    iid = "11111111-1111-1111-1111-111111111111"
    plan = parse_sparql_subset(
        f"SELECT ?o WHERE {{ <{iid}> :发生 ?o }} LIMIT 20"
    )
    assert plan.action == "list_relations"
    assert plan.args["instance_id"] == iid
    assert plan.args["property_label"] == "发生"


def test_forbid_update():
    with pytest.raises(AppError) as ei:
        parse_sparql_subset("INSERT DATA { <a> <b> <c> }")
    assert ei.value.code == ErrorCode.KNOWLEDGE_002


def test_forbid_full_scan():
    with pytest.raises(AppError) as ei:
        parse_sparql_subset("SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10")
    assert ei.value.code == ErrorCode.KNOWLEDGE_002


def test_limit_too_large():
    with pytest.raises(AppError) as ei:
        parse_sparql_subset('SELECT ?s WHERE { ?s rdfs:label "x" } LIMIT 500')
    assert ei.value.code == ErrorCode.KNOWLEDGE_002
