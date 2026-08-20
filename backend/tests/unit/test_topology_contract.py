"""Round-trip + registry tests for the scl-compatible topology contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.schemas.topology import TopologyGraph
from app.topology.node_types import (
    LAYOUT_X_STEP,
    LAYOUT_Y_STEP,
    get_default_registry,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "scl_copy.json"


def _load_raw() -> dict:
    text = FIXTURE.read_text(encoding="utf-8")
    return json.loads(text)


def test_fixture_exists():
    assert FIXTURE.exists(), f"missing fixture {FIXTURE}"


def test_round_trip_structural_equivalence():
    raw = _load_raw()
    graph = TopologyGraph.from_scl(raw)
    dumped = graph.to_scl()

    assert dumped["workflow_id"] == raw["workflow_id"]
    assert dumped["name"] == raw["name"]
    assert dumped["description"] == raw["description"]
    assert dumped["created_at"] == raw["created_at"]
    assert dumped["last_updated"] == raw["last_updated"]
    assert len(dumped["nodes"]) == len(raw["nodes"])
    assert len(dumped["edges"]) == len(raw["edges"])

    raw_nodes = {n["id"]: n for n in raw["nodes"]}
    for node in dumped["nodes"]:
        orig = raw_nodes[node["id"]]
        assert node["label"] == orig["label"]
        assert node["type"] == orig["type"]
        assert node["x"] == orig["x"]
        assert node["y"] == orig["y"]
        assert node["color"] == orig["color"]
        assert node["extension_id"] == orig["extension_id"]
        for key, value in orig["properties"].items():
            assert key in node["properties"], f"missing properties.{key} on {node['id']}"
            assert node["properties"][key] == value

    raw_edges = {e["id"]: e for e in raw["edges"]}
    for edge in dumped["edges"]:
        orig = raw_edges[edge["id"]]
        assert edge["label"] == orig["label"]
        assert edge["source"]["cell"] == orig["source"]["cell"]
        assert edge["target"]["cell"] == orig["target"]["cell"]
        if "port" in orig["source"]:
            assert edge["source"]["port"] == orig["source"]["port"]
        else:
            assert "port" not in edge["source"]
        if "port" in orig["target"]:
            assert edge["target"]["port"] == orig["target"]["port"]
        else:
            assert "port" not in edge["target"]


def test_known_types_match_registry():
    raw = _load_raw()
    graph = TopologyGraph.from_scl(raw)
    warnings = graph.validate_types()
    assert warnings == []
    assert graph.validate_edge_refs() == []

    reg = get_default_registry()
    for node in graph.nodes:
        spec = reg.get(node.type)
        assert node.extension_id == spec.extension_id
        # Sample uses two greens for 业务操作; registry canonical color is #C8E6C9.
        if node.type != "业务操作":
            assert node.color == spec.color


def test_apply_type_defaults_fills_missing_style():
    graph = TopologyGraph(
        workflow_id="w1",
        name="t",
        nodes=[{"id": "n1", "label": "检查日志", "type": "业务操作"}],
        edges=[],
    )
    graph.apply_type_defaults()
    node = graph.nodes[0]
    spec = get_default_registry().get("业务操作")
    assert node.color == spec.color
    assert node.extension_id == spec.extension_id


def test_unknown_type_gets_class_color():
    graph = TopologyGraph(
        workflow_id="w1",
        nodes=[{"id": "n1", "label": "x", "type": "未知类型"}],
    )
    warnings = graph.validate_types()
    assert any("未知类型" in w for w in warnings)
    graph.apply_type_defaults()
    assert graph.nodes[0].color
    assert graph.nodes[0].extension_id is None


def test_dangling_edge_is_warned():
    graph = TopologyGraph(
        workflow_id="w1",
        nodes=[{"id": "n1", "label": "a", "type": "建议"}],
        edges=[
            {
                "id": "e1",
                "source": {"cell": "n1"},
                "target": {"cell": "missing"},
                "label": "是",
            }
        ],
    )
    warnings = graph.validate_edge_refs()
    assert any("missing" in w for w in warnings)


def test_duplicate_node_id_rejected():
    with pytest.raises(ValueError, match="唯一"):
        TopologyGraph(
            workflow_id="w1",
            nodes=[
                {"id": "n1", "label": "a", "type": "故障"},
                {"id": "n1", "label": "b", "type": "建议"},
            ],
        )


def test_layout_grid_constants_match_sample():
    raw = _load_raw()
    xs = sorted({n["x"] for n in raw["nodes"]})
    ys = sorted({n["y"] for n in raw["nodes"]})
    x_steps = [xs[i] - xs[i - 1] for i in range(1, len(xs))]
    y_steps = [ys[i] - ys[i - 1] for i in range(1, len(ys))]
    # Canonical grid is 280×160; the sample has one 260 x-step (hand-tuned).
    assert x_steps.count(LAYOUT_X_STEP) == max(x_steps.count(s) for s in set(x_steps))
    assert set(y_steps) == {LAYOUT_Y_STEP}


def test_sample_has_ungrounded_and_grounded_nodes():
    raw = _load_raw()
    selected = [n["properties"].get("selectedObjectId") for n in raw["nodes"]]
    assert "自定义" in selected
    uuids = [s for s in selected if s and s != "自定义"]
    assert uuids, "sample should also contain grounded instance ids"
