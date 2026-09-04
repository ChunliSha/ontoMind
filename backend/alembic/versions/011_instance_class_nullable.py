"""Allow ontology_instance.class_id to be empty (manual correction).

Revision ID: 011_instance_class_nullable
Revises: 010_qa_session_source
Create Date: 2026-08-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "011_instance_class_nullable"
down_revision = "010_qa_session_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "ontology_instance",
        "class_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
        existing_nullable=False,
    )


def downgrade() -> None:
    op.execute("DELETE FROM ontology_instance WHERE class_id IS NULL")
    op.alter_column(
        "ontology_instance",
        "class_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
        existing_nullable=True,
    )
