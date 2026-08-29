"""MCP admin DTOs (API keys + service registry)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class McpApiKeyCreate(BaseModel):
    name: str = Field(default="", max_length=128)


class McpApiKeyRead(BaseModel):
    id: str
    name: str
    key_prefix: str
    created_at: datetime | None = None
    last_used_at: datetime | None = None


class McpApiKeyCreated(McpApiKeyRead):
    api_key: str


class McpServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    ontology_model_id: str
    url: str = Field(default="", max_length=512)
    tool_names: list[str] = Field(default_factory=list)
    description: str = Field(default="", max_length=2000)


class McpServiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    ontology_model_id: str | None = None
    url: str | None = Field(default=None, max_length=512)
    tool_names: list[str] | None = None
    description: str | None = Field(default=None, max_length=2000)


class McpServiceRead(BaseModel):
    id: str
    name: str
    ontology_model_id: str | None = None
    ontology_model_name: str | None = None
    url: str = ""
    tool_names: list[str] = Field(default_factory=list)
    description: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class McpPublishedTool(BaseModel):
    name: str
    description: str = ""
