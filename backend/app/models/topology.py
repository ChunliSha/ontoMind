"""Business-logic topology ORM (§P0). Independent of BusinessLogicRule."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class BusinessLogicTopology(Base):
    __tablename__ = "business_logic_topology"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    schema_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ontology_schema.id", ondelete="CASCADE"),
        nullable=False,
    )
    schema_version: Mapped[int | None] = mapped_column(Integer)
    ontology_model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ontology_model.id", ondelete="SET NULL"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_file_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    graph: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    grounded_ratio: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    validation: Mapped[dict | None] = mapped_column(JSONB)
    layout_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    extraction_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extraction_task.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    nodes: Mapped[list[BusinessLogicTopologyNode]] = relationship(
        back_populates="topology", cascade="all, delete-orphan"
    )


class BusinessLogicTopologyNode(Base):
    """Per-node grounding audit row (instance id + match evidence)."""

    __tablename__ = "business_logic_topology_node"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    topology_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("business_logic_topology.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_key: Mapped[str] = mapped_column(String(64), nullable=False)
    node_type: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    instance_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ontology_instance.id", ondelete="SET NULL"),
    )
    matched_by: Mapped[str | None] = mapped_column(String(16))
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    evidence: Mapped[dict | None] = mapped_column(JSONB)

    topology: Mapped[BusinessLogicTopology] = relationship(back_populates="nodes")
