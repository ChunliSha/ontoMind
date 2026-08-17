"""Add ontology_instance.schema_version for per-schema version inventory.

Revision ID: 003_instance_schema_version
Revises: 002_llm_models
Create Date: 2026-08-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "003_instance_schema_version"
down_revision = "002_llm_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ontology_instance",
        sa.Column("schema_version", sa.Integer(), nullable=True),
    )
    op.create_index(
        "idx_instance_schema_version",
        "ontology_instance",
        ["schema_id", "schema_version"],
    )
    # Backfill from current schema.version for existing rows
    op.execute(
        """
        UPDATE ontology_instance i
        SET schema_version = s.version
        FROM ontology_schema s
        WHERE i.schema_id = s.id AND i.schema_version IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("idx_instance_schema_version", table_name="ontology_instance")
    op.drop_column("ontology_instance", "schema_version")
