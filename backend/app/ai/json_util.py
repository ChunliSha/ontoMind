"""JSON helpers for LLM responses (fenced blocks and nested payloads)."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def strip_json_fences(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = _FENCE_RE.sub("", text).strip()
    starts_object = bool(text) and text.startswith("{")
    if starts_object:
        return text
    start = text.find("{")
    end = text.rfind("}")
    has_object = start >= 0 and end > start
    if has_object:
        return text[start : end + 1]
    return text


def parse_json_object(raw: str) -> dict[str, Any]:
    text = strip_json_fences(raw)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("模型返回的 JSON 不是对象")
    for key in ("schema", "result", "data", "output"):
        nested = data.get(key)
        has_schema_keys = isinstance(nested, dict) and (
            "classes" in nested or "properties" in nested
        )
        if has_schema_keys:
            return nested
    return data
