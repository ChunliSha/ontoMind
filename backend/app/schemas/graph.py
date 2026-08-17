"""Graph Pydantic DTOs (§7.3 / §9.4)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class GraphNode(BaseModel):
    id: str
    type: Literal["class", "obj_prop", "data_prop", "instance"]
    label: str
    dp: int | None = None
    op: int | None = None
    inst: int | None = None
    classId: str | None = None


class GraphLink(BaseModel):
    source: str
    target: str
    type: Literal["schema_link", "instance_of", "instance_rel"]
    label: str | None = None


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    links: list[GraphLink]
    truncated: bool = False
    message: str | None = None


class GraphNodeDetail(BaseModel):
    id: str
    type: str
    label: str
    details: dict[str, Any] = {}
