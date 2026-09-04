"""Extraction / instance Pydantic DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExtractionTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_type: Literal[
        "schema_induction",
        "instance_unstructured",
        "instance_structured",
        "business_logic",
        "business_logic_topology",
    ]
    status: Literal["pending", "running", "succeeded", "failed"]
    schema_id: str | None = None
    progress: float
    output_summary: dict | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class TaskAccepted(BaseModel):
    task_id: str
    status: Literal["pending"] = "pending"


class UnstructuredExtractionRequest(BaseModel):
    schema_id: str
    file_ids: list[str] = Field(min_length=1)
    ai_config: dict | None = None
    model_id: str | None = None
    # True：抽取前清除本 Schema 当前版本下的非结构化实例，避免重复堆积
    replace_existing: bool = True


class StructuredExtractionRequest(BaseModel):
    schema_id: str
    mapping_ids: list[str] = Field(min_length=1)
    replace_existing: bool = False


class BusinessLogicExtractionRequest(BaseModel):
    ontology_model_id: str | None = None
    schema_id: str | None = None
    file_ids: list[str] = Field(min_length=1)
    ai_config: dict | None = None
    model_id: str | None = None
    schema_version: int | None = None
    type_mapping: dict[str, list[str]] | None = None
    name: str | None = None

    @model_validator(mode="after")
    def _need_target(self) -> BusinessLogicExtractionRequest:
        if not self.ontology_model_id and not self.schema_id:
            raise ValueError("请选择本体模型")
        return self


class ClearInstancesRequest(BaseModel):
    schema_version: int | None = None
    source_types: list[str] | None = None


class ClearInstancesResult(BaseModel):
    deleted: int
    schema_id: str
    schema_version: int | None = None


class InstanceDataValueRead(BaseModel):
    property_id: str
    property_label: str | None = None
    value: str


class InstanceRelationRead(BaseModel):
    property_id: str
    property_label: str | None = None
    object_instance_id: str
    object_instance_label: str | None = None
    object_label: str | None = None
    object_class_label: str | None = None
    direction: str = "out"


class InstanceDataValueWrite(BaseModel):
    property_id: str = Field(min_length=1)
    value: str = Field(min_length=1)


class InstanceRelationWrite(BaseModel):
    property_id: str = Field(min_length=1)
    object_instance_id: str = Field(min_length=1)


class InstanceUpdate(BaseModel):
    """Replace class + data values + outgoing object relations in one save."""

    class_id: str | None = None
    data_values: list[InstanceDataValueWrite] = Field(default_factory=list)
    relations: list[InstanceRelationWrite] = Field(default_factory=list)


class InstanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    schema_id: str
    class_id: str | None = None
    class_label: str | None = None
    label: str
    local_name: str | None = None
    source_type: str
    source_ref: dict | None = None
    confidence: float | None = None
    schema_version: int | None = None
    extraction_task_id: str | None = None
    created_at: datetime
    data_values: list[InstanceDataValueRead] = []
    relations: list[InstanceRelationRead] = []


class InstanceStatsItem(BaseModel):
    class_id: str
    class_label: str
    count: int


class InstanceStatsResponse(BaseModel):
    schema_id: str
    schema_version: int | None = None
    total: int
    by_class: list[InstanceStatsItem]


class InstanceInventoryResponse(BaseModel):
    schema_id: str
    schema_name: str
    schema_version: int
    filter_version: int | None = None
    versions: list[int]
    total: int
    by_class: list[InstanceStatsItem]
    recent_tasks: list[ExtractionTaskRead] = []
