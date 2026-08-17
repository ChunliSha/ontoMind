"""Ontology schema ORM models (§6.2) + graph_cache (§6.7)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class OntologySchema(Base):
    __tablename__ = "ontology_schema"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    base_iri: Mapped[str] = mapped_column(
        String(255), nullable=False, default="http://example.com/ontomind/schema#"
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    change_log: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
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

    classes: Mapped[list[OntologyClass]] = relationship(
        back_populates="schema", cascade="all, delete-orphan"
    )
    properties: Mapped[list[OntologyProperty]] = relationship(
        back_populates="schema", cascade="all, delete-orphan"
    )


class OntologyClass(Base):
    __tablename__ = "ontology_class"
    __table_args__ = (UniqueConstraint("schema_id", "label", name="uq_class_schema_label"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    schema_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ontology_schema.id", ondelete="CASCADE"),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    local_name: Mapped[str | None] = mapped_column(String(128))
    parent_class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ontology_class.id", ondelete="SET NULL")
    )
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    schema: Mapped[OntologySchema] = relationship(back_populates="classes")
    properties: Mapped[list[OntologyProperty]] = relationship(
        back_populates="domain_class",
        foreign_keys="OntologyProperty.domain_class_id",
        cascade="all, delete-orphan",
    )


class OntologyProperty(Base):
    __tablename__ = "ontology_property"
    __table_args__ = (
        UniqueConstraint("domain_class_id", "label", name="uq_prop_domain_label"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    schema_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ontology_schema.id", ondelete="CASCADE"),
        nullable=False,
    )
    domain_class_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ontology_class.id", ondelete="CASCADE"),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    local_name: Mapped[str | None] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    datatype: Mapped[str | None] = mapped_column(String(32))
    range_class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ontology_class.id")
    )
    required: Mapped[bool] = mapped_column(default=False)
    multi: Mapped[bool] = mapped_column(default=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    schema: Mapped[OntologySchema] = relationship(back_populates="properties")
    domain_class: Mapped[OntologyClass] = relationship(
        back_populates="properties", foreign_keys=[domain_class_id]
    )


class GraphCache(Base):
    __tablename__ = "graph_cache"

    schema_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ontology_schema.id", ondelete="CASCADE"),
        primary_key=True,
    )
    mode: Mapped[str] = mapped_column(String(16), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
