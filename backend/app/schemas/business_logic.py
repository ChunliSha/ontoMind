"""Business logic rule Pydantic DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class BusinessLogicRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    schema_id: str
    rule_type: Literal["causality", "constraint"]
    description: str
    condition: dict[str, Any]
    consequence: Any | None = None
    action_required: str | None = None
    severity: str | None = None
    source_doc_id: str | None = None
    extraction_task_id: str | None = None
    created_at: datetime


class BusinessLogicExport(BaseModel):
    business_logic: list[dict[str, Any]]
