"""DTOs for named ontology models (schema version + instances)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class OntologyModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    schema_id: str
    schema_version: int | None = None


class OntologyModelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None


class OntologyModelRead(BaseModel):
    id: str
    name: str
    description: str = ""
    schema_id: str
    schema_name: str
    schema_version: int
    class_count: int = 0
    instance_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
