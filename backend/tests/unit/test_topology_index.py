"""Unit tests for ontology index lookup and class→node-type suggestion."""

from __future__ import annotations

from app.topology.index import IndexedClass, IndexedInstance, OntologyIndex
from app.topology.normalize import normalize_alias
from app.topology.type_mapping import suggest_type_mapping


def _meter_index() -> OntologyIndex:
    classes = [
        IndexedClass("c-op", "操作", local_name="Operation", instance_count=2),
        IndexedClass("c-fault", "故障", local_name="Fault", instance_count=1),
        IndexedClass("c-sug", "建议", local_name="Suggestion", instance_count=1),
        IndexedClass("c-dev", "设备", local_name="Device", instance_count=1),
        IndexedClass("c-person", "人员", local_name="Person", instance_count=0),
    ]
    instances = [
        IndexedInstance(
            id="i-log",
            class_id="c-op",
            class_label="操作",
            label="主站侧日志是否完整",
            local_name="CheckMasterLogs",
            aliases=["检查主站日志完整性"],
            data_values={"接口名称": "检查主站日志完整性", "请求路径": "/api/v1/query_master_logs_complete"},
        ),
        IndexedInstance(
            id="i-dispatch",
            class_id="c-op",
            class_label="操作",
            label="主站召测请求下发",
            local_name="DispatchMasterRequest",
        ),
        IndexedInstance(
            id="i-block",
            class_id="c-fault",
            class_label="故障",
            label="主站任务过多来不及下发",
            data_values={"故障编码": "0010006"},
        ),
        IndexedInstance(
            id="i-sug",
            class_id="c-sug",
            class_label="建议",
            label="定界到主站，排查主站侧其他问题",
        ),
        IndexedInstance(
            id="i-master",
            class_id="c-dev",
            class_label="设备",
            label="主站",
        ),
    ]
    return OntologyIndex(
        schema_id="s1", schema_version=1, classes=classes, instances=instances
    )


def test_normalize_alias_strips_spaces_and_punct():
    assert normalize_alias("主站侧日志是否完整") == normalize_alias("主站侧 日志是否完整")
    assert normalize_alias("Check-Master_Logs") == "checkmasterlogs"


def test_lookup_exact_label():
    idx = _meter_index()
    hit = idx.lookup("主站召测请求下发")
    assert hit.grounded
    assert hit.matched_by == "exact"
    assert hit.instance_id == "i-dispatch"


def test_lookup_by_uuid():
    idx = _meter_index()
    hit = idx.lookup("i-log")
    assert hit.instance_id == "i-log"
    assert hit.matched_by == "exact"


def test_lookup_alias_and_name_like_property():
    idx = _meter_index()
    hit = idx.lookup("检查主站日志完整性")
    assert hit.instance_id == "i-log"
    assert hit.matched_by in {"exact", "normalized"}


def test_lookup_normalized_spacing():
    idx = _meter_index()
    hit = idx.lookup("主站侧 日志是否完整")
    assert hit.instance_id == "i-log"
    assert hit.matched_by == "normalized"


def test_lookup_fuzzy():
    idx = _meter_index()
    hit = idx.lookup("主站任务过多来不及下发了")
    assert hit.instance_id == "i-block"
    assert hit.matched_by == "fuzzy"
    assert hit.score >= 0.82


def test_lookup_unmatched_keeps_candidates():
    idx = _meter_index()
    hit = idx.lookup("完全不相关的句子xyz")
    assert not hit.grounded
    assert hit.matched_by == "unmatched"
    assert hit.candidates


def test_lookup_scoped_to_class():
    idx = _meter_index()
    hit = idx.lookup("主站", class_ids={"c-fault"})
    assert not hit.grounded
    hit2 = idx.lookup("主站", class_ids={"c-dev"})
    assert hit2.instance_id == "i-master"


def test_suggest_maps_operation_fault_suggestion():
    idx = _meter_index()
    result = suggest_type_mapping(idx)
    by_type = {m.type_key: m for m in result.mapping}
    assert "c-op" in by_type["业务操作"].class_ids
    assert "c-fault" in by_type["故障"].class_ids
    assert "c-sug" in by_type["建议"].class_ids
    unmapped_ids = {c.id for c in result.unmapped_classes}
    assert "c-dev" in unmapped_ids
    assert "c-person" in unmapped_ids
    assert by_type["业务操作"].instance_count == 2
