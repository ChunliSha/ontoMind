"""Optional embedding lookup. Phase 1 remains Postgres ILIKE; pgvector is a future index."""

from __future__ import annotations

from app.core.config import settings


def vector_search_enabled() -> bool:
    return bool(settings.KNOWLEDGE_PGVECTOR)
