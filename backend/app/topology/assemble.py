"""Assemble a LogicGraph into an scl-compatible TopologyGraph."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

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

IDENTITY_FIELDS = [
    PropertyFieldSpec(key="name", source="grounding"),
    PropertyFieldSpec(key="selectedObjectId", source="grounding", default=UNGROUNDED_OBJECT_ID),
    PropertyFieldSpec(key="ins_name", source="grounding"),
    PropertyFieldSpec(key="classId", source="grounding"),
    PropertyFieldSpec(key="classLabel", source="grounding"),
]
IDENTITY_KEYS = {field.key for field in IDENTITY_FIELDS}


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
    topo_nodes = [_assemble_node(node, index, reg, mapping) for node in nodes]
    topo_edges = _assemble_edges(edges, mapping)
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
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


def property_template(
    index: OntologyIndex, node_type: str, inst: IndexedInstance | None
) -> list[PropertyFieldSpec]:
    cls = _class_of(index, node_type, inst)
    fields = list(IDENTITY_FIELDS)
    if cls is None:
        return fields
    for label in cls.data_property_labels:
        fields.append(PropertyFieldSpec(key=label, source="instance_data", instance_property=label))
    for label in cls.object_property_labels:
        fields.append(
            PropertyFieldSpec(key=label, source="instance_relation", instance_property=label)
        )
    return fields


def merge_schema_properties(existing: dict | None, fresh: dict) -> dict:
    out = dict(fresh)
    for key, val in (existing or {}).items():
        if key in IDENTITY_KEYS or key not in out:
            continue
        if not _filled(out.get(key)) and _filled(val):
            out[key] = val
    return out


def _class_of(index: OntologyIndex, node_type: str, inst: IndexedInstance | None):
    if inst:
        found = index.classes.get(inst.class_id)
        if found:
            return found
    needle = ((inst.class_label if inst else None) or node_type or "").strip()
    if not needle:
        return None
    for cls in index.classes.values():
        if cls.label == needle or cls.local_name == needle:
            return cls
    return None


def _assemble_node(node: LogicNode, index: OntologyIndex, reg: NodeTypeRegistry, mapping: dict[str, str]):
    nid = mapping.get(node.key) or str(uuid.uuid4())
    mapping[node.key] = nid
    inst = index.instances.get(node.instance_id) if node.instance_id else None
    node_type = (inst.class_label if inst else node.type) or UNGROUNDED_TYPE
    spec = reg.get(node_type) if reg.has(node_type) else None
    template = property_template(index, node_type, inst)
    return TopologyNode(
        id=nid,
        label=node.label or (inst.label if inst else node.key),
        type=node_type,
        color=spec.color if spec else color_for_class(node_type),
        extension_id=spec.extension_id if spec else None,
        properties=assemble_properties(node, inst, template),
    )


def _assemble_edges(edges: list[tuple[str, str, str]], mapping: dict[str, str]) -> list[TopologyEdge]:
    return [
        TopologyEdge(
            id=str(uuid.uuid4()),
            source=TopologyEndpoint(cell=mapping[src]),
            target=TopologyEndpoint(cell=mapping[tgt]),
            label=lab,
        )
        for src, tgt, lab in edges
        if src in mapping and tgt in mapping
    ]


def assemble_properties(node: LogicNode, inst: IndexedInstance | None, template=None) -> dict:
    props: dict = {}
    fields = list(template) if template is not None else list(IDENTITY_FIELDS)
    for field in fields:
        val = _value_for_field(field, node, inst)
        if val is not None:
            props[field.key] = val
        elif field.source in {"instance_data", "instance_relation"}:
            props[field.key] = ""
        elif field.default is not None:
            props[field.key] = field.default
    props.setdefault("name", node.label)
    if inst:
        _apply_instance_payload(props, inst)
    return props


def _value_for_field(field, node: LogicNode, inst: IndexedInstance | None):
    src = field.source
    if src == "grounding":
        return _from_grounding(field, node, inst)
    if src == "instance_data":
        return _from_instance_data(field, inst)
    if src == "instance_relation":
        return _from_instance_relation(field, inst)
    if src == "llm":
        llm_attr = LLM_FIELD.get(field.key)
        return getattr(node, llm_attr, None) if llm_attr else None
    if src == "const":
        return field.default
    return None


def _filled(val) -> bool:
    if val is None:
        return False
    if isinstance(val, str):
        return bool(val.strip())
    return True


def _apply_instance_payload(props: dict, inst: IndexedInstance) -> None:
    props["classId"] = inst.class_id
    props["classLabel"] = inst.class_label
    props.setdefault("ins_name", inst.label)
    for label, value in inst.data_values.items():
        if not label or label in IDENTITY_KEYS or not _filled(value):
            continue
        props[label] = value
    for rel in inst.relations:
        if not rel.property_label or rel.property_label in IDENTITY_KEYS:
            continue
        if _filled(rel.object_label):
            props[rel.property_label] = rel.object_label


def _from_grounding(field, node: LogicNode, inst: IndexedInstance | None):
    if field.key == "selectedObjectId":
        return inst.id if inst else UNGROUNDED_OBJECT_ID
    if field.key in {"name", "ins_name"}:
        return (inst.label if inst else None) or node.label
    if field.key == "classId":
        return inst.class_id if inst else None
    if field.key == "classLabel":
        return inst.class_label if inst else node.type
    return inst.label if inst else node.label


def _from_instance_data(field, inst: IndexedInstance | None):
    if not inst or not field.instance_property:
        return None
    return inst.data_values.get(field.instance_property)


def _from_instance_relation(field, inst: IndexedInstance | None):
    if not inst or not field.instance_property:
        return None
    rel = _find_relation(inst, field.instance_property)
    if not rel:
        return None
    if field.key.endswith("_model"):
        return {"id": rel.object_id, "name": rel.object_label}
    if field.key.endswith("_id"):
        return rel.object_id
    return rel.object_label


def _find_relation(inst: IndexedInstance, prop_hint: str):
    hint = prop_hint or ""
    for rel in inst.relations:
        if hint in rel.property_label or rel.property_label in hint:
            return rel
    if len(inst.relations) == 1:
        return inst.relations[0]
    return None
