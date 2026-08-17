"""Cross-document instance merge key (align extract/populate_ontology)."""

from __future__ import annotations

from app.ai.schema_grounded_instance import _instance_merge_key, _slug


def test_slug_stable():
    assert _slug("主变压器") == _slug(" 主变压器 ")
    assert _slug("1号主变压器") != _slug("主变压器")


def test_merge_key_dedupes_same_mention():
    a = _instance_merge_key("变压器", "主变压器")
    b = _instance_merge_key("变压器", "主变压器")
    c = _instance_merge_key("变压器", "1号主变压器")
    assert a == b
    assert a != c
