"""QA session source: hide MCP chats from the UI history list.

Revision ID: 010_qa_session_source
Revises: 009_mcp_admin
Create Date: 2026-08-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "010_qa_session_source"
down_revision = "009_mcp_admin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "qa_session",
        sa.Column("source", sa.String(16), nullable=False, server_default="qa"),
    )
    op.create_index("ix_qa_session_source", "qa_session", ["source"])
    op.execute(
        """
        UPDATE qa_session
        SET source = 'mcp'
        WHERE id IN (
            SELECT DISTINCT session_id
            FROM knowledge_access_log
            WHERE caller = 'mcp' AND session_id IS NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_qa_session_source", table_name="qa_session")
    op.drop_column("qa_session", "source")
