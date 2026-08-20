"""Business-logic topology tables + extraction_task type.

Revision ID: 005_business_logic_topology
Revises: 004_source_type_len
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "005_business_logic_topology"
down_revision = "004_source_type_len"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_et_type", "extraction_task", type_="check")
    op.create_check_constraint(
        "ck_et_type",
        "extraction_task",
        "task_type IN ("
        "'schema_induction','instance_unstructured','instance_structured',"
        "'business_logic','business_logic_topology'"
        ")",
    )

    op.create_table(
        "business_logic_topology",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "schema_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ontology_schema.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("schema_version", sa.Integer()),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "source_file_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "graph",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("node_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("edge_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("grounded_ratio", sa.Numeric(5, 2)),
        sa.Column("validation", postgresql.JSONB()),
        sa.Column("layout_locked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column(
            "extraction_task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("extraction_task.id", ondelete="SET NULL"),
        ),
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
        sa.CheckConstraint(
            "status IN ('draft','ready','failed')",
            name="ck_blt_status",
        ),
    )
    op.create_index(
        "idx_blt_schema",
        "business_logic_topology",
        ["schema_id", "schema_version"],
    )

    op.create_table(
        "business_logic_topology_node",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "topology_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("business_logic_topology.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_key", sa.String(64), nullable=False),
        sa.Column("node_type", sa.String(32), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column(
            "instance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ontology_instance.id", ondelete="SET NULL"),
        ),
        sa.Column("matched_by", sa.String(16)),
        sa.Column("score", sa.Numeric(5, 4)),
        sa.Column("evidence", postgresql.JSONB()),
        sa.UniqueConstraint("topology_id", "node_key", name="uq_bltn_topo_key"),
        sa.CheckConstraint(
            "matched_by IS NULL OR matched_by IN "
            "('exact','alias','normalized','fuzzy','unmatched','manual')",
            name="ck_bltn_matched_by",
        ),
    )
    op.create_index(
        "idx_bltn_topology",
        "business_logic_topology_node",
        ["topology_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_bltn_topology", table_name="business_logic_topology_node")
    op.drop_table("business_logic_topology_node")
    op.drop_index("idx_blt_schema", table_name="business_logic_topology")
    op.drop_table("business_logic_topology")

    op.drop_constraint("ck_et_type", "extraction_task", type_="check")
    op.create_check_constraint(
        "ck_et_type",
        "extraction_task",
        "task_type IN ("
        "'schema_induction','instance_unstructured','instance_structured',"
        "'business_logic'"
        ")",
    )
