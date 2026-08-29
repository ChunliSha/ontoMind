"""Bounded BFS expand (max hops / max nodes)."""

from app.knowledge.expand import bfs_expand


def _line_graph(n: int):
    labels = {str(i): f"n{i}" for i in range(n)}
    edges = [(str(i), "p", "连到", str(i + 1)) for i in range(n - 1)]
    return labels, edges


def test_expand_two_hops():
    labels, edges = _line_graph(6)
    nodes, links = bfs_expand(["0"], labels, edges, max_hops=2, max_nodes=200)
    assert nodes == ["0", "1", "2"]
    assert {e.object_id for e in links} >= {"1", "2"}


def test_expand_max_nodes():
    labels, edges = _line_graph(20)
    nodes, _links = bfs_expand(["0"], labels, edges, max_hops=3, max_nodes=4)
    assert len(nodes) <= 4


def test_expand_respects_start():
    labels = {"a": "设备A", "b": "故障1", "c": "原因X"}
    edges = [("a", "p1", "发生", "b"), ("b", "p2", "导致", "c")]
    nodes, links = bfs_expand(["a"], labels, edges, max_hops=1, max_nodes=50)
    assert "a" in nodes and "b" in nodes
    assert "c" not in nodes
    assert any(e.property_label == "发生" for e in links)
