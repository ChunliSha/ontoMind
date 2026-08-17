"""LLM model configuration ORM."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LlmModelConfig(Base):
    __tablename__ = "llm_model_config"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    # cloud = 主流云厂商；local = 本地 / 内网自建服务
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="cloud")
    # openai / deepseek / qwen / zhipu / moonshot / ollama / vllm / local_openai / custom / mock
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    api_base: Mapped[str | None] = mapped_column(String(512))
    api_key_enc: Mapped[str | None] = mapped_column(Text)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # active / disabled / failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    last_error: Mapped[str | None] = mapped_column(Text)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extra_config: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
