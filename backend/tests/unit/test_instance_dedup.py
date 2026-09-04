"""Cross-document instance merge key (align extract/populate_ontology)."""

from __future__ import annotations

from app.ai.populate_ontology_pipeline import instance_merge_key, slug


def test_slug_stable():
    assert slug("主变压器") == slug(" 主变压器 ")
    assert slug("1号主变压器") != slug("主变压器")


def test_merge_key_dedupes_same_mention():
    a = instance_merge_key("变压器", "主变压器")
    b = instance_merge_key("变压器", "主变压器")
    c = instance_merge_key("变压器", "1号主变压器")
    assert a == b
    assert a != c
