"""Widen ontology_instance.source_type for structured_mapping.

Revision ID: 004_source_type_len
Revises: 003_instance_schema_version
Create Date: 2026-08-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "004_source_type_len"
down_revision = "003_instance_schema_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "ontology_instance",
        "source_type",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "ontology_instance",
        "source_type",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
        existing_nullable=False,
    )
