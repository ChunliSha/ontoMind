"""LLM provider protocol and AI result envelope (§10)."""

from __future__ import annotations

from typing import Any, Generic, Literal, Protocol, TypeVar
import uuid

from pydantic import BaseModel, Field

from app.topology.logic_graph import LogicGraph

T = TypeVar("T")


class AIResult(BaseModel, Generic[T]):
    success: bool
    result: T | None = None
    confidence: float | None = None
    tokens_used: int | None = None
    latency_ms: int | None = None
    error: str | None = None


class InducedClass(BaseModel):
    label: str
    local_name: str | None = None
    description: str | None = None
    confidence: float | None = None


class InducedProperty(BaseModel):
    class_label: str
    label: str
    kind: Literal["data", "object"]
    datatype: str | None = None
    range_class_label: str | None = None
    required: bool = False
    multi: bool = False
    confidence: float | None = None


class SchemaInductionResult(BaseModel):
    classes: list[InducedClass] = Field(default_factory=list)
    properties: list[InducedProperty] = Field(default_factory=list)


class SchemaSnapshotProperty(BaseModel):
    label: str
    kind: Literal["data", "object"]
    datatype: str | None = None
    range_class_label: str | None = None
    local_name: str | None = None


class SchemaSnapshotClass(BaseModel):
    label: str
    local_name: str | None = None
    properties: list[SchemaSnapshotProperty] = Field(default_factory=list)


class SchemaSnapshot(BaseModel):
    classes: list[SchemaSnapshotClass] = Field(default_factory=list)


class ExtractedDataValue(BaseModel):
    property_label: str
    value: str


class ExtractedRelation(BaseModel):
    property_label: str
    target_instance_label: str


class ExtractedInstance(BaseModel):
    class_label: str
    label: str
    local_name: str | None = None
    source_ref: dict[str, Any] | None = None
    confidence: float | None = None
    data_values: list[ExtractedDataValue] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)


class InstanceExtractionResult(BaseModel):
    instances: list[ExtractedInstance] = Field(default_factory=list)


class BusinessLogicRuleDraft(BaseModel):
    rule_id: str | None = None
    type: Literal["causality", "constraint"]
    description: str
    condition: dict[str, Any]
    consequence: list[str] | None = None
    action_required: str | None = None
    severity: str | None = None
    source_doc: str | None = None


class LLMProvider(Protocol):
    async def induce_schema(
        self, texts: list[str], existing_classes: list[str]
    ) -> AIResult[SchemaInductionResult]: ...

    async def extract_instances(
        self, texts: list[str], schema_snapshot: SchemaSnapshot, task_id: uuid.UUID | None = None
    ) -> AIResult[InstanceExtractionResult]: ...

    async def extract_business_logic(
        self,
        texts: list[str],
        schema_snapshot: SchemaSnapshot,
        instance_labels: list[str],
    ) -> AIResult[list[BusinessLogicRuleDraft]]: ...

    async def extract_business_logic_topology(
        self,
        text: str,
        catalog_by_class: dict[str, list[dict[str, str]]],
    ) -> AIResult[LogicGraph]: ...
