"""End-to-end topology extraction pipeline (chunk → LLM → merge → ground → assemble → layout)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.schemas.topology import TopologyGraph
from app.topology.assemble import assemble_topology
from app.topology.chunking import chunk_documents
from app.topology.grounding import ground_logic_graph
from app.topology.index import OntologyIndex
from app.topology.layout import layout_topology
from app.topology.logic_graph import LogicGraph
from app.topology.merge import merge_by_instance_id, merge_logic_graphs
from app.topology.node_types import NodeTypeRegistry
from app.topology.validate import validate_topology

ExtractFn = Callable[[str, dict[str, list[dict[str, str]]]], Awaitable[LogicGraph]]


def catalog_for_prompt(
    index: OntologyIndex,
    type_to_class_ids: dict[str, set[str]] | None = None,
    *,
    per_class_limit: int = 40,
) -> dict[str, list[dict[str, str]]]:
    """Instance catalog grouped by ontology class label (prompt vocabulary)."""
    catalog: dict[str, list[dict[str, str]]] = {}
    if type_to_class_ids:
        for type_key, class_ids in type_to_class_ids.items():
            items: list[dict[str, str]] = []
            for inst in index.instances_for_classes(class_ids):
                items.append({"id": inst.id, "label": inst.label, "class_id": inst.class_id})
                if len(items) >= per_class_limit:
                    break
            catalog[type_key] = items
        return catalog

    for cls in sorted(index.classes.values(), key=lambda c: c.label):
        items = []
        for inst in index.instances_for_class(cls.id):
            items.append({"id": inst.id, "label": inst.label, "class_id": cls.id})
            if len(items) >= per_class_limit:
                break
        catalog[cls.label] = items
    return catalog


def build_from_logic(
    logic: LogicGraph,
    index: OntologyIndex,
    type_to_class_ids: dict[str, set[str]] | None = None,
    *,
    registry: NodeTypeRegistry | None = None,
    name: str = "",
    layout_locked: bool = False,
) -> tuple[TopologyGraph, list[dict], dict[str, Any]]:
    grounded = ground_logic_graph(logic, index, type_to_class_ids)
    grounded = merge_by_instance_id(grounded)
    edges = [(e.source, e.target, e.label) for e in grounded.edges]
    graph, key_map = assemble_topology(
        grounded.nodes,
        edges,
        index,
        name=name or grounded.name or "business_logic",
        registry=registry,
    )
    layout_topology(graph, locked=layout_locked)
    warnings = validate_topology(graph, registry)
    grounded_n = sum(
        1
        for n in graph.nodes
        if n.properties.get("selectedObjectId") not in (None, "", "自定义")
    )
    stats = {
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "grounded": grounded_n,
        "grounded_ratio": round(100.0 * grounded_n / max(len(graph.nodes), 1), 2),
        "key_map": key_map,
        "audit": [
            {
                "node_key": n.key,
                "node_id": key_map.get(n.key),
                "node_type": n.type,
                "label": n.label,
                "instance_id": n.instance_id,
                "matched_by": n.matched_by,
                "score": n.match_score,
            }
            for n in grounded.nodes
        ],
    }
    return graph, warnings, stats


async def extract_logic_graphs(
    extract: ExtractFn,
    texts: list[str],
    catalog: dict[str, list[dict[str, str]]],
    *,
    on_progress: Callable[[float], Awaitable[None]] | None = None,
    max_chunks: int = 8,
) -> LogicGraph:
    chunks = chunk_documents(texts)[:max_chunks]
    if not chunks:
        raise ValueError("文档无可抽取文本")
    graphs: list[LogicGraph] = []
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        graphs.append(await extract(chunk, catalog))
        await asyncio.sleep(0)
        if on_progress:
            await on_progress(30 + 40 * (i + 1) / total)
    nonempty = [g for g in graphs if g.nodes]
    if not nonempty:
        raise ValueError("模型未抽取出任何业务逻辑节点")
    return merge_logic_graphs(nonempty)
