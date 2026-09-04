"""Structural checks on an assembled topology graph."""

from __future__ import annotations

from collections import defaultdict

from app.schemas.topology import TopologyGraph
from app.topology.node_types import NodeTypeRegistry, get_default_registry


def validate_topology(
    graph: TopologyGraph,
    registry: NodeTypeRegistry | None = None,
) -> list[dict]:
    reg = registry or get_default_registry()
    warnings: list[dict] = []
    ids = graph.node_index()

    for w in graph.validate_edge_refs():
        warnings.append({"level": "error", "code": "dangling_edge", "message": warn})

    out_adj, in_deg = _adjacency(graph, ids)
    _warn_structure(warnings, out_adj, in_deg, ids, graph)
    _warn_roles(warnings, graph, reg)
    _warn_ungrounded(warnings, graph)
    return warnings


def _adjacency(graph, ids):
    out_adj: dict[str, list[str]] = defaultdict(list)
    in_deg: dict[str, int] = {node.id: 0 for node in graph.nodes}
    for edge in graph.edges:
        if edge.source.cell in ids and edge.target.cell in ids:
            out_adj[edge.source.cell].append(edge.target.cell)
            in_deg[edge.target.cell] = in_deg.get(edge.target.cell, 0) + 1
    return out_adj, in_deg


def _warn_structure(warnings, out_adj, in_deg, ids, graph) -> None:
    if _has_cycle(out_adj, list(ids)):
        warnings.append({"level": "warning", "code": "cycle", "message": "拓扑存在环路"})
    roots = [nid for nid, deg in in_deg.items() if deg == 0 and (out_adj.get(nid) or nid in ids)]
    isolated = [
        node.id for node in graph.nodes if in_deg.get(node.id, 0) == 0 and not out_adj.get(node.id)
    ]
    connected_roots = [root for root in roots if root not in isolated]
    if len(connected_roots) > 1:
        warnings.append(
            {
                "level": "warning",
                "code": "multiple_roots",
                "message": f"存在 {len(connected_roots)} 个入度为 0 的根节点",
            }
        )
    if isolated:
        warnings.append(
            {
                "level": "warning",
                "code": "isolated",
                "message": f"{len(isolated)} 个孤立节点",
            }
        )


def _warn_roles(warnings, graph, reg) -> None:
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        outgoing[edge.source.cell].append((edge.label or "").strip())
    for node in graph.nodes:
        spec = reg.get(node.type) if reg.has(node.type) else None
        if spec is None:
            continue
        labels = outgoing.get(node.id, [])
        if spec.role == "terminal" and labels:
            warnings.append(
                {
                    "level": "warning",
                    "code": "terminal_out_edge",
                    "message": f"建议节点「{node.label}」不应有出边",
                }
            )
        if spec.role == "judgement" and labels:
            uniq = {item for item in labels if item}
            if uniq and not uniq <= {"是", "否"}:
                warnings.append(
                    {
                        "level": "info",
                        "code": "branch_label",
                        "message": f"节点「{node.label}」出边标签为 {sorted(uniq)}",
                    }
                )


def _warn_ungrounded(warnings, graph) -> None:
    ungrounded = [
        node.label
        for node in graph.nodes
        if (node.properties or {}).get("selectedObjectId") in (None, "", "自定义")
    ]
    if ungrounded:
        warnings.append(
            {
                "level": "info",
                "code": "ungrounded",
                "message": f"{len(ungrounded)} 个节点未落地到实例",
            }
        )


def _has_cycle(adj: dict[str, list[str]], nodes: list[str]) -> bool:
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in nodes}

    def dfs(u: str) -> bool:
        color[u] = GRAY
        for v in adj.get(u, []):
            if color.get(v, WHITE) == GRAY:
                return True
            if color.get(v, WHITE) == WHITE and dfs(v):
                return True
        color[u] = BLACK
        return False

    return any(color[n] == WHITE and dfs(n) for n in nodes)
