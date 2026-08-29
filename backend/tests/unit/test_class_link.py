"""Generic TBox class linking (no domain synonym tables)."""

from app.knowledge.class_link import (
    extract_type_phrase,
    is_list_question,
    link_class_label,
    looks_like_type_scope,
)


def test_list_question_and_phrase():
    assert is_list_question("有哪些设备？")
    assert extract_type_phrase("有哪些设备？") == "设备"
    assert extract_type_phrase("列出全部人员") == "人员"
    assert looks_like_type_scope("有哪些员工")
    assert not is_list_question("1号主变压器的电压等级")


def test_exact_and_containment():
    labels = ["设备", "人员", "工单", "变压器"]
    assert link_class_label("设备", labels) == "设备"
    assert link_class_label("运维人员", labels) == "人员"
    assert link_class_label("有哪些变压器", labels) == "变压器"


def test_spoken_type_not_forced_by_edit_distance():
    labels = ["人员", "设备", "工单", "变压器"]
    # 员工 vs 人员 and 员工 vs 工单 are both 2-char / distance-2; do not guess.
    assert link_class_label("有哪些员工", labels) is None


def test_instance_like_query_not_forced_to_class():
    labels = ["变压器", "变电站"]
    assert link_class_label("1号主变压器", labels) in {None, "变压器"}


def test_ambiguous_returns_none():
    assert link_class_label("天气", ["人员", "设备", "工单"]) is None
