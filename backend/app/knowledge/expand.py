"""Bounded BFS over instance relation edges (no SQL)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class ExpandEdge:
    subject_id: str
    subject_label: str
    property_id: str
    property_label: str
    object_id: str
    object_label: str
    hop: int


def bfs_expand(
    start_ids: list[str],
    labels: dict[str, str],
    directed_edges: list[tuple[str, str, str, str]],
    *,
    max_hops: int,
    max_nodes: int,
) -> tuple[list[str], list[ExpandEdge]]:
    """Expand from start_ids over directed (subject, property_id, property_label, object) edges."""
    if max_hops < 1 or max_nodes < 1 or not start_ids:
        return [], []
    undirected = _undirected_adj(directed_edges)
    ordered, seen = _seed_nodes(start_ids, max_nodes)
    if len(ordered) >= max_nodes:
        return ordered, []
    edges: list[ExpandEdge] = []
    seen_edge: set[tuple[str, str, str, int]] = set()
    frontier = list(ordered)
    for hop in range(1, max_hops + 1):
        nxt = _walk_frontier(
            frontier, hop, undirected, labels, ordered, seen, seen_edge, edges, max_nodes
        )
        if nxt is None:
            return ordered, edges
        if not nxt:
            break
        frontier = nxt
    return ordered, edges


def _undirected_adj(directed_edges):
    undirected: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
    for subj, prop_id, prop_label, obj in directed_edges:
        undirected[subj].append(("out", prop_id, prop_label, obj))
        undirected[obj].append(("in", prop_id, prop_label, subj))
    return undirected


def _seed_nodes(start_ids: list[str], max_nodes: int) -> tuple[list[str], set[str]]:
    ordered: list[str] = []
    seen: set[str] = set()
    for sid in start_ids:
        if sid in seen:
            continue
        seen.add(sid)
        ordered.append(sid)
        if len(ordered) >= max_nodes:
            break
    return ordered, seen


def _walk_frontier(
    frontier, hop, undirected, labels, ordered, seen, seen_edge, edges, max_nodes
):
    nxt: list[str] = []
    for node in frontier:
        for direction, prop_id, prop_label, neighbor in undirected.get(node, []):
            capped = _visit_neighbor(
                node,
                neighbor,
                direction,
                prop_id,
                prop_label,
                hop,
                labels,
                ordered,
                seen,
                seen_edge,
                edges,
                nxt,
                max_nodes,
            )
            if capped:
                return None
    return nxt


def _visit_neighbor(
    node,
    neighbor,
    direction,
    prop_id,
    prop_label,
    hop,
    labels,
    ordered,
    seen,
    seen_edge,
    edges,
    nxt,
    max_nodes,
) -> bool:
    if direction == "out":
        subj, obj = node, neighbor
    else:
        subj, obj = neighbor, node
    key = (subj, prop_id, obj, hop)
    if key in seen_edge:
        return False
    seen_edge.add(key)
    edges.append(
        ExpandEdge(
            subject_id=subj,
            subject_label=labels.get(subj, subj),
            property_id=prop_id,
            property_label=prop_label,
            object_id=obj,
            object_label=labels.get(obj, obj),
            hop=hop,
        )
    )
    if neighbor not in seen and len(seen) < max_nodes:
        seen.add(neighbor)
        nxt.append(neighbor)
        ordered.append(neighbor)
        return len(ordered) >= max_nodes
    return False
