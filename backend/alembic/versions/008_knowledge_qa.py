"""Knowledge access log + QA session/message tables.

Revision ID: 008_knowledge_qa
Revises: 007_topology_node_type_len
Create Date: 2026-08-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "008_knowledge_qa"
down_revision = "007_topology_node_type_len"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_access_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("caller", sa.String(16), nullable=False),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column("ontology_model_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ontology_model.id", ondelete="SET NULL")),
        sa.Column("session_id", postgresql.UUID(as_uuid=True)),
        sa.Column("trace_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("plan", postgresql.JSONB()),
        sa.Column("request_meta", postgresql.JSONB()),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("empty_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error", sa.Text()),
    )
    op.create_index("ix_knowledge_access_log_created_at", "knowledge_access_log", ["created_at"])
    op.create_index("ix_knowledge_access_log_caller", "knowledge_access_log", ["caller"])
    op.create_index("ix_knowledge_access_log_tool_name", "knowledge_access_log", ["tool_name"])
    op.create_index("ix_knowledge_access_log_ontology_model_id", "knowledge_access_log", ["ontology_model_id"])
    op.create_index("ix_knowledge_access_log_session_id", "knowledge_access_log", ["session_id"])
    op.create_index("ix_knowledge_access_log_trace_id", "knowledge_access_log", ["trace_id"])

    op.create_table(
        "qa_session",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "ontology_model_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ontology_model.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "llm_model_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("llm_model_config.id", ondelete="SET NULL"),
        ),
        sa.Column("title", sa.String(255), nullable=False, server_default=""),
        sa.Column("resolved_entities", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_qa_session_ontology_model_id", "qa_session", ["ontology_model_id"])

    op.create_table(
        "qa_message",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("qa_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidences", postgresql.JSONB()),
        sa.Column("plan", postgresql.JSONB()),
        sa.Column("tool_trace", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_qa_message_session_id", "qa_message", ["session_id"])


def downgrade() -> None:
    op.drop_table("qa_message")
    op.drop_table("qa_session")
    op.drop_table("knowledge_access_log")
