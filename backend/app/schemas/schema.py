"""Schema / Class / Property Pydantic DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SchemaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    base_iri: str | None = None


class SchemaUpdate(BaseModel):
    name: str | None = None
    base_iri: str | None = None


class SchemaPublishRequest(BaseModel):
    change_log: str | None = None


class SchemaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    base_iri: str
    status: Literal["draft", "published"]
    version: int
    change_log: str | None = None
    source: str
    class_count: int = 0
    property_count: int = 0
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ClassCreate(BaseModel):
    label: str = Field(min_length=1, max_length=128)
    local_name: str | None = None
    parent_class_id: str | None = None
    description: str | None = None


class ClassUpdate(BaseModel):
    label: str | None = None
    local_name: str | None = None
    parent_class_id: str | None = None
    description: str | None = None


class ClassRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    schema_id: str
    label: str
    local_name: str | None = None
    parent_class_id: str | None = None
    description: str | None = None
    source: str
    cnt: int = 0  # property count for chip list
    created_at: datetime


class PropertyCreate(BaseModel):
    label: str = Field(min_length=1, max_length=128)
    local_name: str | None = None
    kind: Literal["data", "object"]
    datatype: str | None = None
    range_class_id: str | None = None
    required: bool = False
    multi: bool = False


class PropertyUpdate(BaseModel):
    label: str | None = None
    local_name: str | None = None
    kind: Literal["data", "object"] | None = None
    datatype: str | None = None
    range_class_id: str | None = None
    domain_class_id: str | None = None
    required: bool | None = None
    multi: bool | None = None


class PropertyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    schema_id: str
    domain_class_id: str
    label: str
    local_name: str | None = None
    kind: Literal["data", "object"]
    datatype: str | None = None
    range_class_id: str | None = None
    range_class_label: str | None = None
    required: bool
    multi: bool
    source: Literal["manual", "ai"]
    confidence: float | None = None
    created_at: datetime


class SchemaInduceRequest(BaseModel):
    file_ids: list[str]
    model_id: str | None = None
    ai_config: dict | None = None
