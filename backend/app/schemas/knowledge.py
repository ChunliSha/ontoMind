"""DTOs for the Knowledge Service REST API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.knowledge.evidence import Evidence
from app.schemas.ontology_model import OntologyModelRead


class KnowledgeClassRead(BaseModel):
    id: str
    label: str
    local_name: str | None = None
    description: str | None = None
    parent_class_id: str | None = None


class KnowledgePropertyRead(BaseModel):
    id: str
    label: str
    local_name: str | None = None
    kind: str
    datatype: str | None = None
    domain_class_id: str
    domain_class_label: str | None = None
    range_class_id: str | None = None
    range_class_label: str | None = None
    required: bool = False
    multi: bool = False


class KnowledgeSchemaRead(BaseModel):
    ontology_model_id: str
    ontology_model_name: str
    schema_id: str
    schema_name: str
    schema_version: int
    classes: list[KnowledgeClassRead] = Field(default_factory=list)
    properties: list[KnowledgePropertyRead] = Field(default_factory=list)


class KnowledgeInstanceHit(BaseModel):
    id: str
    label: str
    class_id: str
    class_label: str | None = None
    local_name: str | None = None
    score: float = 0.0
    schema_id: str | None = None


class KnowledgeDataValue(BaseModel):
    property_id: str
    property_label: str | None = None
    value: str


class KnowledgeRelation(BaseModel):
    id: str | None = None
    direction: str = "out"
    property_id: str
    property_label: str | None = None
    other_instance_id: str
    other_instance_label: str | None = None
    other_class_label: str | None = None


class KnowledgeInstanceDetail(BaseModel):
    id: str
    label: str
    class_id: str
    class_label: str | None = None
    local_name: str | None = None
    schema_id: str
    schema_version: int | None = None
    source_type: str | None = None
    source_ref: dict[str, Any] | None = None
    data_values: list[KnowledgeDataValue] = Field(default_factory=list)
    relations: list[KnowledgeRelation] = Field(default_factory=list)
    evidences: list[Evidence] = Field(default_factory=list)


class KnowledgeSearchResponse(BaseModel):
    items: list[KnowledgeInstanceHit]
    evidences: list[Evidence] = Field(default_factory=list)
    empty_hit: bool = False


class KnowledgeExpandRequest(BaseModel):
    ontology_model_id: str
    start_ids: list[str] = Field(min_length=1)
    max_hops: int = 1
    max_nodes: int = 200
    predicates: list[str] | None = None


class KnowledgeExpandNode(BaseModel):
    id: str
    label: str
    class_label: str | None = None
    hop: int = 0


class KnowledgeExpandLink(BaseModel):
    subject_id: str
    subject_label: str
    property_id: str
    property_label: str
    object_id: str
    object_label: str
    hop: int


class KnowledgeExpandResponse(BaseModel):
    nodes: list[KnowledgeExpandNode]
    links: list[KnowledgeExpandLink]
    evidences: list[Evidence] = Field(default_factory=list)
    truncated: bool = False


class KnowledgeAccessLogRead(BaseModel):
    id: str
    created_at: datetime | None = None
    caller: str
    tool_name: str
    ontology_model_id: str | None = None
    session_id: str | None = None
    trace_id: str = ""
    latency_ms: int = 0
    empty_hit: bool = False
    error: str | None = None
    request_meta: dict[str, Any] | None = None


class KnowledgeModelList(BaseModel):
    items: list[OntologyModelRead]
    total: int


class SparqlSubsetRequest(BaseModel):
    ontology_model_id: str
    query: str = Field(min_length=1, max_length=4000)
