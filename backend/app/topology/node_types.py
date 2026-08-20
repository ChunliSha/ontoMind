"""Configurable node-type registry for business-logic topology graphs.

MVP ships three seeded types (业务操作 / 故障 / 建议). Adding a type is a
config change, not a code-path fork: color, extension_id, role, and
property-assembly sources all live on the spec.
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, Field

LAYOUT_X_STEP = 280
LAYOUT_Y_STEP = 160
UNGROUNDED_OBJECT_ID = "自定义"
UNGROUNDED_TYPE = "未落地"

# Stable pastel palette for ontology-class node coloring.
CLASS_PALETTE = [
    "#C8E6C9",
    "#BBDEFB",
    "#FFE0B2",
    "#E1BEE7",
    "#B2EBF2",
    "#F8BBD0",
    "#DCEDC8",
    "#D1C4E9",
    "#FFCCBC",
    "#B3E5FC",
    "#FFF9C4",
    "#C5CAE9",
]


def color_for_class(label: str) -> str:
    key = (label or UNGROUNDED_TYPE).strip() or UNGROUNDED_TYPE
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()
    return CLASS_PALETTE[int(digest, 16) % len(CLASS_PALETTE)]

PropertySource = Literal[
    "grounding",
    "instance_data",
    "instance_relation",
    "llm",
    "const",
]
NodeRole = Literal["judgement", "terminal"]


class PropertyFieldSpec(BaseModel):
    """How one `properties` key is filled during graph assembly."""

    key: str
    source: PropertySource
    # Ontology data/object property label to look up when source is instance_*.
    instance_property: str | None = None
    default: Any = None
    required: bool = False


class NodeTypeSpec(BaseModel):
    type_key: str
    color: str
    extension_id: str
    role: NodeRole
    # Keywords used by P1 auto-suggest to map ontology classes → this type.
    class_keywords: list[str] = Field(default_factory=list)
    properties_template: list[PropertyFieldSpec] = Field(default_factory=list)

    def property_keys(self) -> set[str]:
        return {f.key for f in self.properties_template}


_COMMON_IDENTITY = [
    PropertyFieldSpec(key="name", source="grounding"),
    PropertyFieldSpec(key="description", source="instance_data", instance_property="描述"),
    PropertyFieldSpec(key="selectedObjectId", source="grounding", default=UNGROUNDED_OBJECT_ID),
    PropertyFieldSpec(key="ins_name", source="grounding"),
    PropertyFieldSpec(key="relatedDevice", source="instance_relation", instance_property="关联设备"),
    PropertyFieldSpec(key="relatedDevice_id", source="instance_relation", instance_property="关联设备"),
    PropertyFieldSpec(key="relatedDevice_model", source="instance_relation", instance_property="关联设备"),
]

_OPERATION_FIELDS = [
    *_COMMON_IDENTITY,
    PropertyFieldSpec(key="step1Type", source="llm", default="接口调用"),
    PropertyFieldSpec(key="interfaceName", source="instance_data", instance_property="接口名称"),
    PropertyFieldSpec(key="requestMethod", source="instance_data", instance_property="请求方法", default="POST"),
    PropertyFieldSpec(key="requestPath", source="instance_data", instance_property="请求路径"),
    PropertyFieldSpec(key="requestParams", source="instance_data", instance_property="请求参数"),
    PropertyFieldSpec(key="responseParams", source="instance_data", instance_property="响应参数"),
    PropertyFieldSpec(key="userGuideContent", source="llm", default=""),
    PropertyFieldSpec(key="step1Analysis", source="llm", default=""),
    PropertyFieldSpec(key="judgementContent", source="llm", default=""),
]

_FAULT_FIELDS = [
    *_COMMON_IDENTITY,
    PropertyFieldSpec(key="step1Type", source="llm", default="用户指导"),
    PropertyFieldSpec(key="userGuideContent", source="llm", default=""),
    PropertyFieldSpec(key="step1Analysis", source="llm", default=""),
    PropertyFieldSpec(key="judgementContent", source="llm", default=""),
]

_SUGGESTION_FIELDS = [
    *_COMMON_IDENTITY,
    PropertyFieldSpec(key="step1Type", source="const", default="总结"),
    PropertyFieldSpec(key="summaryContent", source="llm", default=""),
    PropertyFieldSpec(key="faultCause", source="instance_relation", instance_property="故障原因"),
    PropertyFieldSpec(key="faultCause_id", source="instance_data", instance_property="故障编码"),
    PropertyFieldSpec(key="faultCause_model", source="instance_relation", instance_property="故障原因"),
]


DEFAULT_NODE_TYPES: list[NodeTypeSpec] = [
    NodeTypeSpec(
        type_key="业务操作",
        color="#C8E6C9",
        extension_id="operation_node_20251126_f5b8c2",
        role="judgement",
        class_keywords=["操作", "业务操作", "检查", "Operation", "Action"],
        properties_template=_OPERATION_FIELDS,
    ),
    NodeTypeSpec(
        type_key="故障",
        color="#FFCDD2",
        extension_id="fault_node_20251126_e4a7b1",
        role="judgement",
        class_keywords=["故障", "Fault", "异常"],
        properties_template=_FAULT_FIELDS,
    ),
    NodeTypeSpec(
        type_key="建议",
        color="#BBDEFB",
        extension_id="suggestion_node_20251126_g6c9d3",
        role="terminal",
        class_keywords=["建议", "Suggestion", "处理建议", "结论"],
        properties_template=_SUGGESTION_FIELDS,
    ),
]


class NodeTypeRegistry:
    def __init__(self, specs: list[NodeTypeSpec] | None = None) -> None:
        self._by_key = {s.type_key: s for s in (specs or DEFAULT_NODE_TYPES)}

    def get(self, type_key: str) -> NodeTypeSpec:
        spec = self._by_key.get(type_key)
        if spec is None:
            known = ", ".join(self._by_key)
            raise KeyError(f"未知节点类型 {type_key!r}，已注册: {known}")
        return spec

    def has(self, type_key: str) -> bool:
        return type_key in self._by_key

    def all(self) -> list[NodeTypeSpec]:
        return list(self._by_key.values())

    def type_keys(self) -> list[str]:
        return list(self._by_key)


def get_default_registry() -> NodeTypeRegistry:
    return NodeTypeRegistry()
