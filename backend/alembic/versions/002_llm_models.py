"""Alembic migration: llm_model_config + seed mock default.

Revision ID: 002_llm_models
Revises: 001_initial
Create Date: 2026-08-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "002_llm_models"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_model_config",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="cloud"),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("api_base", sa.String(512)),
        sa.Column("api_key_enc", sa.Text()),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("last_error", sa.Text()),
        sa.Column("last_tested_at", sa.DateTime(timezone=True)),
        sa.Column("extra_config", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.UniqueConstraint("name", name="uq_llm_model_name"),
        sa.CheckConstraint("source IN ('cloud','local')", name="ck_llm_source"),
        sa.CheckConstraint(
            "provider IN ('openai','azure_openai','deepseek','qwen','zhipu','moonshot','ollama','vllm','local_openai','custom','mock')",
            name="ck_llm_provider",
        ),
        sa.CheckConstraint("status IN ('active','disabled','failed')", name="ck_llm_status"),
    )
    op.create_index("ix_llm_model_default", "llm_model_config", ["is_default"])

    # 内置 Mock，保证未配置真实模型时抽取链路仍可演示
    op.execute(
        """
        INSERT INTO llm_model_config (name, source, provider, api_base, model_name, is_default, status)
        VALUES ('内置 Mock（演示）', 'local', 'mock', NULL, 'mock', true, 'active')
        """
    )


def downgrade() -> None:
    op.drop_index("ix_llm_model_default", table_name="llm_model_config")
    op.drop_table("llm_model_config")
