"""Named ontology models (schema version + instances).

Revision ID: 006_ontology_model
Revises: 005_business_logic_topology
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "006_ontology_model"
down_revision = "005_business_logic_topology"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ontology_model",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "schema_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ontology_schema.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.UniqueConstraint("name", name="uq_ontology_model_name"),
    )
    op.create_index("idx_ontology_model_schema", "ontology_model", ["schema_id", "schema_version"])

    op.add_column(
        "business_logic_topology",
        sa.Column(
            "ontology_model_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ontology_model.id", ondelete="SET NULL"),
        ),
    )
    op.create_index(
        "idx_blt_ontology_model",
        "business_logic_topology",
        ["ontology_model_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_blt_ontology_model", table_name="business_logic_topology")
    op.drop_column("business_logic_topology", "ontology_model_id")
    op.drop_index("idx_ontology_model_schema", table_name="ontology_model")
    op.drop_table("ontology_model")
