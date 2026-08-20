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
        warnings.append({"level": "error", "code": "dangling_edge", "message": w})

    out_adj: dict[str, list[str]] = defaultdict(list)
    in_deg: dict[str, int] = {n.id: 0 for n in graph.nodes}
    for e in graph.edges:
        if e.source.cell in ids and e.target.cell in ids:
            out_adj[e.source.cell].append(e.target.cell)
            in_deg[e.target.cell] = in_deg.get(e.target.cell, 0) + 1

    if _has_cycle(out_adj, list(ids)):
        warnings.append({"level": "warning", "code": "cycle", "message": "拓扑存在环路"})

    roots = [nid for nid, d in in_deg.items() if d == 0 and (out_adj.get(nid) or nid in ids)]
    isolated = [
        n.id for n in graph.nodes if in_deg.get(n.id, 0) == 0 and not out_adj.get(n.id)
    ]
    connected_roots = [r for r in roots if r not in isolated]
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

    outgoing: dict[str, list[str]] = defaultdict(list)
    for e in graph.edges:
        outgoing[e.source.cell].append((e.label or "").strip())

    for n in graph.nodes:
        spec = reg.get(n.type) if reg.has(n.type) else None
        if spec is None:
            continue
        labels = outgoing.get(n.id, [])
        if spec.role == "terminal" and labels:
            warnings.append(
                {
                    "level": "warning",
                    "code": "terminal_out_edge",
                    "message": f"建议节点「{n.label}」不应有出边",
                }
            )
        if spec.role == "judgement" and labels:
            uniq = {x for x in labels if x}
            if uniq and not uniq <= {"是", "否"}:
                warnings.append(
                    {
                        "level": "info",
                        "code": "branch_label",
                        "message": f"节点「{n.label}」出边标签为 {sorted(uniq)}",
                    }
                )

    ungrounded = [
        n.label
        for n in graph.nodes
        if (n.properties or {}).get("selectedObjectId") in (None, "", "自定义")
    ]
    if ungrounded:
        warnings.append(
            {
                "level": "info",
                "code": "ungrounded",
                "message": f"{len(ungrounded)} 个节点未落地到实例",
            }
        )
    return warnings


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
