"""Layered grid layout + port derivation for scl-compatible graphs."""

from __future__ import annotations

from collections import defaultdict, deque

from app.schemas.topology import TopologyEndpoint, TopologyGraph
from app.topology.node_types import LAYOUT_X_STEP, LAYOUT_Y_STEP

X_ORIGIN = -268
Y_ORIGIN = -168


def layout_topology(graph: TopologyGraph, *, locked: bool = False) -> TopologyGraph:
    if locked or not graph.nodes:
        _derive_ports(graph)
        return graph

    ids = [n.id for n in graph.nodes]
    outgoing: dict[str, list[str]] = defaultdict(list)
    incoming: dict[str, list[str]] = defaultdict(list)
    for e in graph.edges:
        outgoing[e.source.cell].append(e.target.cell)
        incoming[e.target.cell].append(e.source.cell)

    components = _weak_components(ids, outgoing, incoming)
    cursor_x = X_ORIGIN
    for comp in components:
        layers = _layers(comp, outgoing, incoming)
        width = max((len(row) for row in layers), default=1)
        for li, row in enumerate(layers):
            for si, nid in enumerate(row):
                node = graph.node_index()[nid]
                node.y = Y_ORIGIN + li * LAYOUT_Y_STEP
                node.x = cursor_x - si * LAYOUT_X_STEP
        cursor_x -= max(width, 1) * LAYOUT_X_STEP

    _derive_ports(graph)
    return graph


def _weak_components(
    ids: list[str],
    outgoing: dict[str, list[str]],
    incoming: dict[str, list[str]],
) -> list[list[str]]:
    seen: set[str] = set()
    comps: list[list[str]] = []
    undirected: dict[str, list[str]] = defaultdict(list)
    for u, vs in outgoing.items():
        for v in vs:
            undirected[u].append(v)
            undirected[v].append(u)
    for u, vs in incoming.items():
        for v in vs:
            undirected[u].append(v)
            undirected[v].append(u)
    for nid in ids:
        if nid in seen:
            continue
        q = [nid]
        seen.add(nid)
        acc = []
        while q:
            u = q.pop()
            acc.append(u)
            for v in undirected.get(u, []):
                if v not in seen and v in ids:
                    seen.add(v)
                    q.append(v)
        comps.append(acc)
    comps.sort(key=lambda c: -len(c))
    return comps


def _layers(
    comp: list[str],
    outgoing: dict[str, list[str]],
    incoming: dict[str, list[str]],
) -> list[list[str]]:
    """Longest-path layers from roots. Cycles (common in 业务逻辑) must not loop forever."""
    comp_set = set(comp)
    n = len(comp)
    indeg = {nid: sum(1 for p in incoming.get(nid, []) if p in comp_set) for nid in comp}
    roots = [nid for nid in comp if indeg[nid] == 0] or [comp[0]]
    layer_of: dict[str, int] = {}
    q: deque[str] = deque()
    for r in roots:
        layer_of[r] = 0
        q.append(r)
    visits = {nid: 0 for nid in comp}
    max_depth = max(n - 1, 0)
    while q:
        u = q.popleft()
        for v in outgoing.get(u, []):
            if v not in comp_set:
                continue
            nxt = layer_of[u] + 1
            if nxt > max_depth:
                continue
            if v not in layer_of or nxt > layer_of[v]:
                layer_of[v] = nxt
                visits[v] += 1
                if visits[v] <= n:
                    q.append(v)
    for nid in comp:
        layer_of.setdefault(nid, 0)
    max_l = max(layer_of.values(), default=0)
    rows: list[list[str]] = [[] for _ in range(max_l + 1)]
    for nid in comp:
        rows[layer_of[nid]].append(nid)
    return rows


def _derive_ports(graph: TopologyGraph) -> None:
    idx = graph.node_index()
    for e in graph.edges:
        src, tgt = idx.get(e.source.cell), idx.get(e.target.cell)
        if not src or not tgt:
            continue
        dx = float(tgt.x) - float(src.x)
        dy = float(tgt.y) - float(src.y)
        if abs(dy) >= abs(dx):
            if dy >= 0:
                e.source = TopologyEndpoint(cell=src.id, port="port-bottom")
                e.target = TopologyEndpoint(cell=tgt.id, port="port-top")
            else:
                e.source = TopologyEndpoint(cell=src.id, port="port-top")
                e.target = TopologyEndpoint(cell=tgt.id, port="port-bottom")
        else:
            if dx < 0:
                e.source = TopologyEndpoint(cell=src.id, port="port-left")
                e.target = TopologyEndpoint(cell=tgt.id, port="port-right")
            else:
                e.source = TopologyEndpoint(cell=src.id, port="port-right")
                e.target = TopologyEndpoint(cell=tgt.id, port="port-left")
