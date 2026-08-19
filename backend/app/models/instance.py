"""Ontology instance ORM models (§6.5)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class OntologyInstance(Base):
    __tablename__ = "ontology_instance"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    schema_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ontology_schema.id", ondelete="CASCADE"),
        nullable=False,
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ontology_class.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    local_name: Mapped[str | None] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[dict | None] = mapped_column(JSONB)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    schema_version: Mapped[int | None] = mapped_column(Integer)
    extraction_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extraction_task.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    data_values: Mapped[list[InstanceDataValue]] = relationship(
        back_populates="instance", cascade="all, delete-orphan"
    )
    subject_relations: Mapped[list[InstanceRelation]] = relationship(
        back_populates="subject",
        foreign_keys="InstanceRelation.subject_instance_id",
        cascade="all, delete-orphan",
    )


class InstanceDataValue(Base):
    __tablename__ = "instance_data_value"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ontology_instance.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ontology_property.id", ondelete="CASCADE"),
        nullable=False,
    )
    value: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    instance: Mapped[OntologyInstance] = relationship(back_populates="data_values")


class InstanceRelation(Base):
    __tablename__ = "instance_relation"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    subject_instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ontology_instance.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ontology_property.id", ondelete="CASCADE"),
        nullable=False,
    )
    object_instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ontology_instance.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    subject: Mapped[OntologyInstance] = relationship(
        back_populates="subject_relations", foreign_keys=[subject_instance_id]
    )
