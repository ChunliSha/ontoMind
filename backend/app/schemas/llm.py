"""LLM model config Pydantic DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ProviderLiteral = Literal[
    "openai",
    "azure_openai",
    "deepseek",
    "qwen",
    "zhipu",
    "moonshot",
    "ollama",
    "vllm",
    "local_openai",
    "custom",
]
SourceLiteral = Literal["cloud", "local"]
StatusLiteral = Literal["active", "disabled", "failed"]


class LlmModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    source: SourceLiteral = "cloud"
    provider: ProviderLiteral
    api_base: str | None = None
    api_key: str | None = None
    model_name: str = Field(min_length=1, max_length=128)
    is_default: bool = False
    extra_config: dict[str, Any] | None = None


class LlmModelUpdate(BaseModel):
    name: str | None = None
    source: SourceLiteral | None = None
    provider: ProviderLiteral | None = None
    api_base: str | None = None
    api_key: str | None = None  # None = 不修改；空串 = 清空
    model_name: str | None = None
    is_default: bool | None = None
    status: StatusLiteral | None = None
    extra_config: dict[str, Any] | None = None


class LlmModelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    source: SourceLiteral
    provider: ProviderLiteral
    api_base: str | None
    has_api_key: bool
    model_name: str
    is_default: bool
    status: StatusLiteral
    last_error: str | None = None
    last_tested_at: datetime | None = None
    extra_config: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class LlmModelTestResult(BaseModel):
    ok: bool
    message: str
    latency_ms: int | None = None


class LlmPreset(BaseModel):
    """前端「从主流模板导入」用的预设。"""

    id: str
    name: str
    source: SourceLiteral
    provider: ProviderLiteral
    api_base: str | None
    model_name: str
    hint: str
