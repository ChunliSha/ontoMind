"""MCP API keys and MCP service registry.

Revision ID: 009_mcp_admin
Revises: 008_knowledge_qa
Create Date: 2026-08-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "009_mcp_admin"
down_revision = "008_knowledge_qa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_api_key",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(128), nullable=False, server_default=""),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_mcp_api_key_key_hash", "mcp_api_key", ["key_hash"], unique=True)
    op.create_index("ix_mcp_api_key_created_at", "mcp_api_key", ["created_at"])

    op.create_table(
        "mcp_service",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "ontology_model_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ontology_model.id", ondelete="SET NULL"),
        ),
        sa.Column("url", sa.String(512), nullable=False, server_default=""),
        sa.Column("tool_names", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_mcp_service_name", "mcp_service", ["name"], unique=True)
    op.create_index("ix_mcp_service_ontology_model_id", "mcp_service", ["ontology_model_id"])


def downgrade() -> None:
    op.drop_table("mcp_service")
    op.drop_table("mcp_api_key")
