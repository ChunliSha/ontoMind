"""Data source Pydantic DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DbSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    db_type: Literal["postgres", "mysql", "gaussdb"]
    host: str
    port: int = Field(ge=1, le=65535)
    database_name: str
    username: str
    password: str


class DbSourceUpdate(BaseModel):
    name: str | None = None
    db_type: Literal["postgres", "mysql", "gaussdb"] | None = None
    host: str | None = None
    port: int | None = None
    database_name: str | None = None
    username: str | None = None
    password: str | None = None


class DbSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    db_type: str
    host: str
    port: int
    database_name: str
    username: str
    status: str
    last_error: str | None = None
    table_count: int | None = 0
    last_synced_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class TableColumnRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    column_name: str
    data_type: str
    is_primary_key: bool
    ordinal: int


class TableRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    table_schema: str
    table_name: str
    row_count: int | None = None
    column_count: int | None = None
    selected_for_modeling: bool
    is_generated: bool
    columns: list[TableColumnRead] = []


class TableSelectionPatch(BaseModel):
    selected_table_ids: list[str] = Field(default_factory=list, alias="table_ids")
    # 前端发 table_ids；也接受 selected_table_ids
    model_config = ConfigDict(populate_by_name=True)


class ConnectionTestResult(BaseModel):
    ok: bool
    message: str | None = None
    table_count: int | None = None


class FileCreateMeta(BaseModel):
    storage_backend: Literal["local", "minio"] = "local"


class FileUpdate(BaseModel):
    name: str | None = None
    extracted_text: str | None = None


class FileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    file_type: str
    storage_backend: str
    storage_path: str
    size_bytes: int
    status: str
    error_message: str | None = None
    standard_md_path: str | None = None
    ontology_md_path: str | None = None
    created_at: datetime
    updated_at: datetime


class FilePreview(BaseModel):
    id: str
    name: str
    status: str
    preview_text: str | None = None
    truncated: bool = False


class BuildTableSqlResponse(BaseModel):
    ddl: str
    suggested_table_name: str
    columns: list[dict]


class MaterializeTableRequest(BaseModel):
    ddl: str | None = None
    table_name: str | None = None
    data_source_id: str | None = None
