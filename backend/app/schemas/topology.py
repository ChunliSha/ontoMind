"""JSON contract for business-logic topology graphs (scl_copy.json isomorphic)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.topology.node_types import NodeTypeRegistry, get_default_registry


class TopologyEndpoint(BaseModel):
    model_config = ConfigDict(extra="allow")

    cell: str
    port: str | None = None


class TopologyNode(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    label: str
    type: str
    x: float | int = 0
    y: float | int = 0
    color: str | None = None
    extension_id: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)

    @field_validator("label", mode="before")
    @classmethod
    def _label_str(cls, v: Any) -> str:
        return str(v).strip() if v is not None else ""


class TopologyEdge(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    source: TopologyEndpoint
    target: TopologyEndpoint
    label: str = ""


class TopologyGraph(BaseModel):
    """Top-level scl-compatible workflow JSON."""

    model_config = ConfigDict(extra="allow")

    workflow_id: str
    name: str = ""
    description: str = ""
    created_at: str | None = None
    last_updated: str | None = None
    nodes: list[TopologyNode] = Field(default_factory=list)
    edges: list[TopologyEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self) -> TopologyGraph:
        node_ids = [n.id for n in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("nodes[].id 必须唯一")
        edge_ids = [e.id for e in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("edges[].id 必须唯一")
        return self

    def node_index(self) -> dict[str, TopologyNode]:
        return {n.id: n for n in self.nodes}

    def apply_type_defaults(self, registry: NodeTypeRegistry | None = None) -> TopologyGraph:
        """Fill missing color / extension_id. Class-typed nodes use a stable hash color."""
        from app.topology.node_types import color_for_class

        reg = registry or get_default_registry()
        for node in self.nodes:
            if reg.has(node.type):
                spec = reg.get(node.type)
                if not node.color:
                    node.color = spec.color
                if not node.extension_id:
                    node.extension_id = spec.extension_id
            elif not node.color:
                node.color = color_for_class(node.type)
        return self

    def validate_types(self, registry: NodeTypeRegistry | None = None) -> list[str]:
        """Return warnings for types not in the registry. Does not raise."""
        reg = registry or get_default_registry()
        return [
            f"节点 {n.id} 类型未注册: {n.type!r}"
            for n in self.nodes
            if not reg.has(n.type)
        ]

    def validate_edge_refs(self) -> list[str]:
        ids = set(self.node_index())
        warnings: list[str] = []
        for e in self.edges:
            if e.source.cell not in ids:
                warnings.append(f"边 {e.id} source.cell 不存在: {e.source.cell}")
            if e.target.cell not in ids:
                warnings.append(f"边 {e.id} target.cell 不存在: {e.target.cell}")
        return warnings

    def to_scl(self, *, exclude_none: bool = True) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude_none=exclude_none)

    @classmethod
    def from_scl(cls, data: dict[str, Any]) -> TopologyGraph:
        return cls.model_validate(data)


class TypeMappingCandidateRead(BaseModel):
    class_id: str
    class_label: str
    local_name: str | None = None
    instance_count: int
    type_key: str
    score: float
    reasons: list[str] = Field(default_factory=list)


class TypeMappingItemRead(BaseModel):
    type_key: str
    class_ids: list[str] = Field(default_factory=list)
    class_labels: list[str] = Field(default_factory=list)
    instance_count: int = 0
    candidates: list[TypeMappingCandidateRead] = Field(default_factory=list)


class UnmappedClassRead(BaseModel):
    class_id: str
    class_label: str
    local_name: str | None = None
    instance_count: int = 0


class TypeMappingSuggestResponse(BaseModel):
    schema_id: str
    schema_version: int | None = None
    instance_count: int
    mapping: list[TypeMappingItemRead]
    unmapped_classes: list[UnmappedClassRead] = Field(default_factory=list)


class CatalogInstanceRead(BaseModel):
    id: str
    label: str
    local_name: str | None = None
    class_id: str
    class_label: str


class TypeCatalogItemRead(BaseModel):
    type_key: str
    class_ids: list[str] = Field(default_factory=list)
    instances: list[CatalogInstanceRead] = Field(default_factory=list)


class InstanceCatalogResponse(BaseModel):
    schema_id: str
    schema_version: int | None = None
    mapping: list[TypeMappingItemRead]
    by_type: list[TypeCatalogItemRead]
    instances: list[CatalogInstanceRead] = Field(default_factory=list)


class NodeTypeRead(BaseModel):
    type_key: str
    color: str
    extension_id: str
    role: str


class TopologySummary(BaseModel):
    id: str
    schema_id: str
    schema_version: int | None = None
    ontology_model_id: str | None = None
    name: str
    description: str = ""
    node_count: int = 0
    edge_count: int = 0
    grounded_ratio: float | None = None
    layout_locked: bool = False
    status: str = "draft"
    extraction_task_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TopologyRead(TopologySummary):
    source_file_ids: list[str] = Field(default_factory=list)
    graph: dict[str, Any] = Field(default_factory=dict)
    validation: dict | None = None
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    type_mapping: dict[str, list[str]] = Field(default_factory=dict)


class TopologyPatchRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    layout_locked: bool | None = None
    graph: dict[str, Any] | None = None
    remount: "TopologyRemountRequest | None" = None
    add_edge: "TopologyEdgeWrite | None" = None
    delete_edge_ids: list[str] | None = None
    update_node: "TopologyNodeWrite | None" = None


class TopologyRemountRequest(BaseModel):
    node_id: str
    instance_id: str | None = None


class TopologyEdgeWrite(BaseModel):
    source_id: str
    target_id: str
    label: str = ""


class TopologyNodeWrite(BaseModel):
    id: str
    label: str | None = None
    x: float | None = None
    y: float | None = None
    properties: dict[str, Any] | None = None
