"""Assemble a LogicGraph into an scl-compatible TopologyGraph."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.schemas.topology import TopologyEdge, TopologyEndpoint, TopologyGraph, TopologyNode
from app.topology.index import IndexedInstance, OntologyIndex
from app.topology.logic_graph import LogicNode
from app.topology.node_types import (
    UNGROUNDED_OBJECT_ID,
    UNGROUNDED_TYPE,
    NodeTypeRegistry,
    PropertyFieldSpec,
    color_for_class,
    get_default_registry,
)

LLM_FIELD = {
    "description": "description",
    "judgementContent": "judgement_content",
    "step1Type": "step1_type",
    "step1Analysis": "step1_analysis",
    "userGuideContent": "user_guide_content",
    "summaryContent": "summary_content",
    "interfaceName": "interface_name",
    "requestMethod": "request_method",
    "requestPath": "request_path",
    "requestParams": "request_params",
    "responseParams": "response_params",
}

_GENERIC_FIELDS = [
    PropertyFieldSpec(key="name", source="grounding"),
    PropertyFieldSpec(key="description", source="llm"),
    PropertyFieldSpec(key="selectedObjectId", source="grounding", default=UNGROUNDED_OBJECT_ID),
    PropertyFieldSpec(key="ins_name", source="grounding"),
    PropertyFieldSpec(key="classId", source="grounding"),
    PropertyFieldSpec(key="classLabel", source="grounding"),
    PropertyFieldSpec(key="judgementContent", source="llm"),
    PropertyFieldSpec(key="step1Analysis", source="llm"),
]


def assemble_topology(
    nodes: list[LogicNode],
    edges: list[tuple[str, str, str]],
    index: OntologyIndex,
    *,
    name: str = "",
    description: str = "",
    registry: NodeTypeRegistry | None = None,
    key_to_id: dict[str, str] | None = None,
) -> tuple[TopologyGraph, dict[str, str]]:
    reg = registry or get_default_registry()
    mapping = key_to_id or {}
    topo_nodes: list[TopologyNode] = []
    for node in nodes:
        nid = mapping.get(node.key) or str(uuid.uuid4())
        mapping[node.key] = nid
        inst = index.instances.get(node.instance_id) if node.instance_id else None
        node_type = (inst.class_label if inst else node.type) or UNGROUNDED_TYPE
        spec = reg.get(node_type) if reg.has(node_type) else None
        color = spec.color if spec else color_for_class(node_type)
        ext = spec.extension_id if spec else None
        template = spec.properties_template if spec else _GENERIC_FIELDS
        props = assemble_properties(node, inst, template)
        topo_nodes.append(
            TopologyNode(
                id=nid,
                label=node.label or (inst.label if inst else node.key),
                type=node_type,
                color=color,
                extension_id=ext,
                properties=props,
            )
        )
    topo_edges = [
        TopologyEdge(
            id=str(uuid.uuid4()),
            source=TopologyEndpoint(cell=mapping[s]),
            target=TopologyEndpoint(cell=mapping[t]),
            label=lab,
        )
        for s, t, lab in edges
        if s in mapping and t in mapping
    ]
    now = datetime.now().isoformat(timespec="microseconds")
    graph = TopologyGraph(
        workflow_id=uuid.uuid4().hex,
        name=name,
        description=description,
        created_at=now,
        last_updated=now,
        nodes=topo_nodes,
        edges=topo_edges,
    )
    return graph, mapping


def assemble_properties(node: LogicNode, inst: IndexedInstance | None, template=None) -> dict:
    props: dict = {}
    fields = list(template) if template else _GENERIC_FIELDS
    for field in fields:
        val = _value_for_field(field, node, inst)
        if val is not None:
            props[field.key] = val
        elif field.default is not None:
            props[field.key] = field.default
    props.setdefault("name", node.label)
    if inst:
        props["classId"] = inst.class_id
        props["classLabel"] = inst.class_label
        props.setdefault("ins_name", inst.label)
    for key, attr in LLM_FIELD.items():
        extra = getattr(node, attr, None)
        if extra and key not in props:
            props[key] = extra
    return props


def _value_for_field(field, node: LogicNode, inst: IndexedInstance | None):
    src = field.source
    if src == "grounding":
        if field.key == "selectedObjectId":
            return inst.id if inst else UNGROUNDED_OBJECT_ID
        if field.key in {"name", "ins_name"}:
            return (inst.label if inst else None) or node.label
        if field.key == "classId":
            return inst.class_id if inst else None
        if field.key == "classLabel":
            return inst.class_label if inst else node.type
        return inst.label if inst else node.label
    if src == "instance_data":
        if inst and field.instance_property and field.instance_property in inst.data_values:
            return inst.data_values[field.instance_property]
        llm_attr = LLM_FIELD.get(field.key)
        if llm_attr:
            return getattr(node, llm_attr, None)
        return None
    if src == "instance_relation" and inst and field.instance_property:
        rel = _find_relation(inst, field.instance_property)
        if not rel:
            return None
        if field.key.endswith("_model"):
            return {"id": rel.object_id, "name": rel.object_label}
        if field.key.endswith("_id"):
            return rel.object_id
        return rel.object_label
    if src == "llm":
        llm_attr = LLM_FIELD.get(field.key)
        return getattr(node, llm_attr, None) if llm_attr else None
    if src == "const":
        return field.default
    return None


def _find_relation(inst: IndexedInstance, prop_hint: str):
    hint = prop_hint or ""
    for rel in inst.relations:
        if hint in rel.property_label or rel.property_label in hint:
            return rel
    if len(inst.relations) == 1:
        return inst.relations[0]
    return None
