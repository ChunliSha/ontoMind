"""OntoMind FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.db.session import AsyncSessionLocal
from app.models.extraction import ExtractionTask

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ontomind")


async def _cleanup_orphan_tasks() -> None:
    """Mark in-memory-lost `pending`/`running` tasks as failed after process restart (§7.5 / P9)."""


    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                update(ExtractionTask)
                .where(ExtractionTask.status.in_(("pending", "running")))
                .values(
                    status="failed",
                    error_message="服务重启，进行中的任务已中断（孤儿任务清理）",
                    finished_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
            if result.rowcount:
                logger.warning("cleaned %s orphan extraction task(s)", result.rowcount)
    except Exception:  # noqa: BLE001 — 启动时库不可达不应阻断 API（例如本机 VPN 分流未生效）
        logger.exception("orphan task cleanup skipped (database unreachable)")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await _cleanup_orphan_tasks()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="OntoMind API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(api_router)

    @app.get("/health")
    async def health():
        return {"status": "ok", "llm_provider": settings.LLM_PROVIDER}

    return app


app = create_app()
