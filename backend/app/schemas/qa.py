"""QA session and chat DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.knowledge.evidence import Evidence


class QaSessionCreate(BaseModel):
    ontology_model_id: str
    model_id: str | None = None


class QaSessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class QaSessionSummary(BaseModel):
    id: str
    ontology_model_id: str
    llm_model_id: str | None = None
    title: str = ""
    message_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class QaMessageRead(BaseModel):
    id: str
    role: str
    content: str
    evidences: list[Evidence] = Field(default_factory=list)
    plan: dict[str, Any] | None = None
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime | None = None


class QaSessionRead(BaseModel):
    id: str
    ontology_model_id: str
    llm_model_id: str | None = None
    title: str = ""
    resolved_entities: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    messages: list[QaMessageRead] = Field(default_factory=list)


class QaChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    model_id: str | None = None


class QaChatResponse(BaseModel):
    session_id: str
    answer: str
    evidences: list[Evidence] = Field(default_factory=list)
    plan: dict[str, Any] | None = None
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    resolved_entities: dict[str, Any] | None = None
