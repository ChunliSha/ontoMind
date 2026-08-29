"""Hard limits for knowledge queries (hops, rows, timeout, concurrency)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

from app.core.config import settings
from app.core.exceptions import AppError, ErrorCode

T = TypeVar("T")

_semaphore: asyncio.Semaphore | None = None


def default_limit() -> int:
    return int(settings.KNOWLEDGE_DEFAULT_LIMIT)


def max_limit() -> int:
    return int(settings.KNOWLEDGE_MAX_LIMIT)


def max_hops() -> int:
    return int(settings.KNOWLEDGE_MAX_HOPS)


def max_nodes() -> int:
    return int(settings.KNOWLEDGE_MAX_NODES)


def query_timeout_s() -> float:
    return float(settings.KNOWLEDGE_TIMEOUT_S)


def concurrency_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(max(1, int(settings.KNOWLEDGE_MAX_CONCURRENCY)))
    return _semaphore


def clamp_limit(value: int | None, *, default: int | None = None, hard_max: int | None = None) -> int:
    cap = hard_max if hard_max is not None else max_limit()
    n = default_limit() if default is None else default
    if value is not None:
        n = int(value)
    if n < 1:
        raise AppError(ErrorCode.KNOWLEDGE_002, message="limit 至少为 1", field="limit")
    if n > cap:
        raise AppError(
            ErrorCode.KNOWLEDGE_002,
            message=f"limit 不能超过 {cap}",
            field="limit",
        )
    return n


def clamp_hops(value: int | None) -> int:
    n = 1 if value is None else int(value)
    cap = max_hops()
    if n < 1:
        raise AppError(ErrorCode.KNOWLEDGE_002, message="max_hops 至少为 1", field="max_hops")
    if n > cap:
        raise AppError(
            ErrorCode.KNOWLEDGE_002,
            message=f"max_hops 不能超过 {cap}",
            field="max_hops",
        )
    return n


def clamp_nodes(value: int | None) -> int:
    n = max_nodes() if value is None else int(value)
    cap = max_nodes()
    if n < 1:
        raise AppError(ErrorCode.KNOWLEDGE_002, message="max_nodes 至少为 1", field="max_nodes")
    if n > cap:
        raise AppError(
            ErrorCode.KNOWLEDGE_002,
            message=f"max_nodes 不能超过 {cap}",
            field="max_nodes",
        )
    return n


async def run_bounded(coro: Awaitable[T], *, timeout: float | None = None) -> T:
    """Run a knowledge query under concurrency + timeout limits."""
    seconds = query_timeout_s() if timeout is None else timeout
    try:
        async with asyncio.timeout(seconds):
            async with concurrency_semaphore():
                return await coro
    except TimeoutError as exc:
        raise AppError(ErrorCode.KNOWLEDGE_002, message=f"查询超时（{seconds:.0f}s）") from exc
