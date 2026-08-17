"""Mapping Pydantic DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SourceFieldRead(BaseModel):
    column_name: str
    data_type: str
    is_primary_key: bool
    ordinal: int


class TargetPropertyRead(BaseModel):
    id: str | None = None  # None for pseudo instance_uri
    label: str
    kind: Literal["instance_uri", "data", "object"]
    datatype: str | None = None
    target_kind: Literal["instance_uri", "property"]


class MappingBindingCreate(BaseModel):
    target_kind: Literal["instance_uri", "property"]
    target_property_id: str | None = None
    source_column: str


class MappingCreate(BaseModel):
    schema_id: str
    class_id: str
    table_id: str
    bindings: list[MappingBindingCreate] = Field(min_length=1)


class MappingBindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    target_kind: str
    target_property_id: str | None = None
    source_column: str


class MappingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    schema_id: str
    class_id: str
    table_id: str
    bindings: list[MappingBindingRead] = []
    created_at: datetime
    updated_at: datetime
