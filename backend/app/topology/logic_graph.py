"""LLM-emitted logic graph (no coordinates). Intermediate form before grounding/layout."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LogicNode(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    key: str
    type: str
    label: str
    instance_ref: str | None = None
    description: str | None = None
    judgement_content: str | None = Field(default=None, alias="judgementContent")
    step1_type: str | None = Field(default=None, alias="step1Type")
    step1_analysis: str | None = Field(default=None, alias="step1Analysis")
    user_guide_content: str | None = Field(default=None, alias="userGuideContent")
    summary_content: str | None = Field(default=None, alias="summaryContent")
    interface_name: str | None = Field(default=None, alias="interfaceName")
    request_method: str | None = Field(default=None, alias="requestMethod")
    request_path: str | None = Field(default=None, alias="requestPath")
    request_params: str | None = Field(default=None, alias="requestParams")
    response_params: str | None = Field(default=None, alias="responseParams")
    instance_id: str | None = None
    matched_by: str | None = None
    match_score: float | None = None

    @field_validator("key", "label", "type", mode="before")
    @classmethod
    def _strip(cls, v):
        return str(v).strip() if v is not None else v


class LogicEdge(BaseModel):
    source: str
    target: str
    label: str = ""

    @field_validator("source", "target", "label", mode="before")
    @classmethod
    def _endpoint(cls, v):
        if isinstance(v, dict):
            return str(v.get("cell") or v.get("key") or v.get("label") or "")
        return str(v or "")


class LogicGraph(BaseModel):
    name: str = ""
    nodes: list[LogicNode] = Field(default_factory=list)
    edges: list[LogicEdge] = Field(default_factory=list)

    def node_by_key(self) -> dict[str, LogicNode]:
        return {n.key: n for n in self.nodes}


def logic_graph_from_llm(data: Any) -> LogicGraph:
    """Coerce common LLM JSON shapes into a LogicGraph."""
    if isinstance(data, list):
        payload: dict[str, Any] = {"nodes": data, "edges": []}
    elif isinstance(data, dict):
        payload = data
        if "nodes" not in payload:
            for key in ("graph", "result", "data", "output", "topology"):
                nested = payload.get(key)
                if isinstance(nested, dict) and "nodes" in nested:
                    payload = nested
                    break
    else:
        raise ValueError("模型返回的 JSON 不是对象")

    nodes_in = payload.get("nodes") or []
    edges_in = payload.get("edges") or payload.get("links") or []
    nodes: list[dict[str, Any]] = []
    for i, raw in enumerate(nodes_in):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        if not str(item.get("key") or "").strip():
            item["key"] = str(item.get("id") or f"n{i + 1}")
        if not str(item.get("type") or "").strip():
            item["type"] = str(item.get("node_type") or item.get("nodeType") or "")
        if not str(item.get("label") or "").strip():
            item["label"] = str(item.get("name") or item.get("title") or item["key"])
        if not item.get("instance_ref"):
            item["instance_ref"] = (
                item.get("instanceRef")
                or item.get("instance")
                or item.get("selectedObjectId")
                or item.get("ins_name")
            )
        nodes.append(item)

    edges: list[dict[str, Any]] = []
    for raw in edges_in:
        if not isinstance(raw, dict):
            continue
        edges.append(
            {
                "source": raw.get("source") or raw.get("from") or raw.get("src"),
                "target": raw.get("target") or raw.get("to") or raw.get("dst"),
                "label": raw.get("label") or raw.get("condition") or "",
            }
        )
    return LogicGraph.model_validate(
        {"name": payload.get("name") or "", "nodes": nodes, "edges": edges}
    )
