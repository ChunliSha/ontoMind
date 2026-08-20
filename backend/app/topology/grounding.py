"""Ground logic-graph nodes onto ontology instances."""

from __future__ import annotations

from app.topology.index import OntologyIndex
from app.topology.logic_graph import LogicGraph
from app.topology.node_types import UNGROUNDED_TYPE
from app.topology.normalize import normalize_alias


def ground_logic_graph(
    graph: LogicGraph,
    index: OntologyIndex,
    type_to_class_ids: dict[str, set[str]] | None = None,
) -> LogicGraph:
    """Resolve nodes onto instances by id / label. Class scope is optional."""
    class_by_label = {normalize_alias(c.label): c for c in index.classes.values()}
    for node in graph.nodes:
        query = (node.instance_ref or node.label or "").strip()
        class_ids = None
        if type_to_class_ids:
            class_ids = type_to_class_ids.get(node.type) or None
        hit = index.lookup(query, class_ids=class_ids)
        if hit.grounded:
            node.instance_id = hit.instance_id
            node.matched_by = hit.matched_by
            node.match_score = hit.score
            inst = index.instances.get(hit.instance_id or "")
            if inst:
                node.type = inst.class_label
                if not node.label:
                    node.label = inst.label
        else:
            node.instance_id = None
            node.matched_by = "unmatched"
            node.match_score = 0.0
            cls = class_by_label.get(normalize_alias(node.type))
            if cls:
                node.type = cls.label
            elif not (node.type or "").strip():
                node.type = UNGROUNDED_TYPE
    return graph
