"""Widen topology node_type to hold ontology class labels.

Revision ID: 007_topology_node_type_len
Revises: 006_ontology_model
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "007_topology_node_type_len"
down_revision = "006_ontology_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "business_logic_topology_node",
        "node_type",
        existing_type=sa.String(32),
        type_=sa.String(128),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "business_logic_topology_node",
        "node_type",
        existing_type=sa.String(128),
        type_=sa.String(32),
        existing_nullable=False,
    )
