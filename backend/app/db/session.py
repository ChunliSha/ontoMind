"""Async database engine and session dependency."""

from __future__ import annotations

import threading
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

_worker_sessionmaker = threading.local()


def _make_engine(*, pool_size: int, max_overflow: int):
    return create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=30,
    )


engine = _make_engine(pool_size=15, max_overflow=30)
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


def create_worker_sessionmaker() -> tuple:
    """Engine + sessionmaker for a background extraction thread (own event loop)."""
    eng = _make_engine(pool_size=3, max_overflow=5)
    sm = async_sessionmaker(
        eng,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    return eng, sm


def set_worker_sessionmaker(sm) -> None:
    _worker_sessionmaker.sm = sm


def clear_worker_sessionmaker() -> None:
    if hasattr(_worker_sessionmaker, "sm"):
        delattr(_worker_sessionmaker, "sm")


def session_scope():
    """Session factory for the current thread: worker-local or the API engine."""
    sm = getattr(_worker_sessionmaker, "sm", None)
    return (sm or AsyncSessionLocal)()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
