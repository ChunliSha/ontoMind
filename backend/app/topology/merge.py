"""Merge chunk-level logic graphs into one panoramic graph."""

from __future__ import annotations

from app.topology.logic_graph import LogicEdge, LogicGraph, LogicNode
from app.topology.normalize import normalize_alias


def _node_identity(node: LogicNode) -> str:
    ref = node.instance_id or node.instance_ref or node.label
    return f"{node.type}::{normalize_alias(ref)}"


def merge_logic_graphs(graphs: list[LogicGraph]) -> LogicGraph:
    merged_nodes: dict[str, LogicNode] = {}
    key_alias: dict[str, str] = {}  # original key -> canonical key
    name = ""
    seq = 0

    for g in graphs:
        if g.name and not name:
            name = g.name
        local: dict[str, str] = {}
        for node in g.nodes:
            ident = _node_identity(node)
            if ident in merged_nodes:
                canon = merged_nodes[ident].key
                _fill_missing(merged_nodes[ident], node)
            else:
                seq += 1
                canon = node.key or f"n{seq}"
                # Avoid key collision across chunks
                if canon in {n.key for n in merged_nodes.values()}:
                    canon = f"{canon}_{seq}"
                cloned = node.model_copy(update={"key": canon})
                merged_nodes[ident] = cloned
            local[node.key] = merged_nodes[ident].key
            key_alias[node.key] = merged_nodes[ident].key

        for edge in g.edges:
            src = local.get(edge.source) or key_alias.get(edge.source)
            tgt = local.get(edge.target) or key_alias.get(edge.target)
            if not src:
                src = _resolve_by_label(merged_nodes, edge.source)
            if not tgt:
                tgt = _resolve_by_label(merged_nodes, edge.target)
            if src and tgt:
                key_alias[edge.source] = src
                key_alias[edge.target] = tgt
            # stash on graph via side channel below
            edge.source = src or edge.source
            edge.target = tgt or edge.target

    edges: list[LogicEdge] = []
    seen: set[tuple[str, str, str]] = set()
    for g in graphs:
        for edge in g.edges:
            src = key_alias.get(edge.source, edge.source)
            tgt = key_alias.get(edge.target, edge.target)
            if src not in {n.key for n in merged_nodes.values()}:
                src = _resolve_by_label(merged_nodes, src) or src
            if tgt not in {n.key for n in merged_nodes.values()}:
                tgt = _resolve_by_label(merged_nodes, tgt) or tgt
            keys = {n.key for n in merged_nodes.values()}
            if src not in keys or tgt not in keys or src == tgt:
                continue
            sig = (src, tgt, (edge.label or "").strip())
            if sig in seen:
                continue
            seen.add(sig)
            edges.append(LogicEdge(source=src, target=tgt, label=edge.label or ""))

    return LogicGraph(name=name, nodes=list(merged_nodes.values()), edges=edges)


def merge_by_instance_id(graph: LogicGraph) -> LogicGraph:
    """After grounding, collapse nodes that mapped to the same instance."""
    by_inst: dict[str, LogicNode] = {}
    remap: dict[str, str] = {}
    kept: list[LogicNode] = []
    for node in graph.nodes:
        if node.instance_id:
            if node.instance_id in by_inst:
                canon = by_inst[node.instance_id]
                remap[node.key] = canon.key
                _fill_missing(canon, node)
                continue
            by_inst[node.instance_id] = node
        kept.append(node)
        remap[node.key] = node.key

    edges: list[LogicEdge] = []
    seen: set[tuple[str, str, str]] = set()
    for e in graph.edges:
        src, tgt = remap.get(e.source, e.source), remap.get(e.target, e.target)
        if src == tgt:
            continue
        sig = (src, tgt, (e.label or "").strip())
        if sig in seen:
            continue
        seen.add(sig)
        edges.append(LogicEdge(source=src, target=tgt, label=e.label or ""))
    return LogicGraph(name=graph.name, nodes=kept, edges=edges)


def _fill_missing(dst: LogicNode, src: LogicNode) -> None:
    for field in (
        "instance_ref",
        "description",
        "judgement_content",
        "step1_type",
        "step1_analysis",
        "user_guide_content",
        "summary_content",
        "interface_name",
        "request_method",
        "request_path",
        "request_params",
        "response_params",
        "instance_id",
        "matched_by",
        "match_score",
    ):
        if getattr(dst, field) in (None, "") and getattr(src, field) not in (None, ""):
            setattr(dst, field, getattr(src, field))


def _resolve_by_label(merged: dict[str, LogicNode], token: str) -> str | None:
    ntok = normalize_alias(token)
    if not ntok:
        return None
    for node in merged.values():
        if normalize_alias(node.key) == ntok or normalize_alias(node.label) == ntok:
            return node.key
        if node.instance_ref and normalize_alias(node.instance_ref) == ntok:
            return node.key
    return None
