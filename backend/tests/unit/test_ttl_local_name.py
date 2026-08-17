"""Unit test for Chinese label → local_name rule."""

from app.rdf.ttl_builder import label_to_local_name


def test_ascii_label_kept():
    assert label_to_local_name("Equipment") == "Equipment"


def test_chinese_label_stable():
    a = label_to_local_name("设备")
    b = label_to_local_name("设备")
    assert a == b
    assert a.replace("_", "").isalnum()
    assert a[0].isalpha() or a.startswith("c_")


def test_collision_suffix():
    existing = {label_to_local_name("设备")}
    other = label_to_local_name("设备", existing=existing)
    assert other != list(existing)[0]
