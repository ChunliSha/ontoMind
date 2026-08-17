"""Helpers for converting ORM UUIDs to str in DTOs."""

from __future__ import annotations

import uuid
from typing import Any


def uid(value: uuid.UUID | str | None) -> str | None:
    if value is None:
        return None
    return str(value)


def parse_uuid(value: str, *, field: str | None = None) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError) as exc:
        from app.core.exceptions import AppError, ErrorCode

        raise AppError(ErrorCode.VALIDATION_ERROR, message=f"无效的 UUID: {value}", field=field) from exc


def orm_to_dict(obj: Any, *fields: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for f in fields:
        v = getattr(obj, f)
        if isinstance(v, uuid.UUID):
            data[f] = str(v)
        else:
            data[f] = v
    return data
