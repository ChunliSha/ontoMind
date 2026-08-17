"""Dashboard Pydantic DTOs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class DashboardSummary(BaseModel):
    data_source_count: int
    structured_count: int = 0
    unstructured_count: int = 0
    schema_count: int
    class_count: int = 0
    instance_count: int
    graph_count: int = 0  # published schemas usable as graphs
    graph_version_count: int = 0  # 前端卡片字段名
    data_source_trend: int | None = None
    schema_trend: int | None = None
    instance_trend: int | None = None


class ActivityItem(BaseModel):
    id: str
    action: str
    resource_type: str
    resource_id: str | None = None
    resource_name: str | None = None
    created_at: datetime


class DashboardActivity(BaseModel):
    items: list[ActivityItem]
