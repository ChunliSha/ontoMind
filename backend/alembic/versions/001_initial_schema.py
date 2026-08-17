"""Initial OntoMind schema (§6 all tables + pgcrypto + created_by).

Revision ID: 001_initial
Revises:
Create Date: 2026-08-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PG 13+ 核心已提供 gen_random_uuid()，不依赖 pgcrypto。
    # 部分精简安装没有 contrib，CREATE EXTENSION 会失败，故仅在可用时尝试。
    op.execute(
        """
        DO $$
        BEGIN
          CREATE EXTENSION IF NOT EXISTS pgcrypto;
        EXCEPTION
          WHEN OTHERS THEN
            RAISE NOTICE 'pgcrypto unavailable, continuing with core gen_random_uuid()';
        END $$;
        """
    )

    op.create_table(
        "data_source_db",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("db_type", sa.String(16), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("database_name", sa.String(128), nullable=False),
        sa.Column("username", sa.String(128), nullable=False),
        sa.Column("password_enc", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("last_error", sa.Text()),
        sa.Column("table_count", sa.Integer(), server_default="0"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.CheckConstraint("db_type IN ('postgres','mysql','gaussdb')", name="ck_dsdb_type"),
        sa.CheckConstraint("status IN ('pending','connected','failed','syncing')", name="ck_dsdb_status"),
    )

    op.create_table(
        "data_source_table",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("data_source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("data_source_db.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_schema", sa.String(128), nullable=False, server_default="public"),
        sa.Column("table_name", sa.String(128), nullable=False),
        sa.Column("row_count", sa.BigInteger()),
        sa.Column("column_count", sa.Integer()),
        sa.Column("selected_for_modeling", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_generated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.UniqueConstraint("data_source_id", "table_schema", "table_name", name="uq_dst_schema_name"),
    )

    op.create_table(
        "data_source_table_column",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("table_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("data_source_table.id", ondelete="CASCADE"), nullable=False),
        sa.Column("column_name", sa.String(128), nullable=False),
        sa.Column("data_type", sa.String(64), nullable=False),
        sa.Column("is_primary_key", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
    )

    op.create_table(
        "data_source_file",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("file_type", sa.String(16), nullable=False),
        sa.Column("storage_backend", sa.String(16), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text()),
        sa.Column("standard_md_path", sa.Text()),
        sa.Column("ontology_md_path", sa.Text()),
        sa.Column("extracted_text", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.CheckConstraint("storage_backend IN ('local','minio')", name="ck_dsf_storage"),
        sa.CheckConstraint("status IN ('pending','parsing','ready','failed')", name="ck_dsf_status"),
    )

    op.create_table(
        "ontology_schema",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("base_iri", sa.String(255), nullable=False, server_default="http://example.com/ontomind/schema#"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("change_log", sa.Text()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("published_by", postgresql.UUID(as_uuid=True)),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.CheckConstraint("status IN ('draft','published')", name="ck_os_status"),
        sa.CheckConstraint("source IN ('manual','ai_induced','imported_ttl')", name="ck_os_source"),
    )

    op.create_table(
        "ontology_class",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("schema_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ontology_schema.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("local_name", sa.String(128)),
        sa.Column("parent_class_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ontology_class.id", ondelete="SET NULL")),
        sa.Column("description", sa.Text()),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.CheckConstraint("source IN ('manual','ai')", name="ck_oc_source"),
        sa.UniqueConstraint("schema_id", "label", name="uq_class_schema_label"),
    )

    op.create_table(
        "ontology_property",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("schema_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ontology_schema.id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain_class_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ontology_class.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("local_name", sa.String(128)),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("datatype", sa.String(32)),
        sa.Column("range_class_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ontology_class.id")),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("multi", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("confidence", sa.Numeric(5, 2)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.CheckConstraint("kind IN ('data','object')", name="ck_op_kind"),
        sa.CheckConstraint("source IN ('manual','ai')", name="ck_op_source"),
        sa.UniqueConstraint("domain_class_id", "label", name="uq_prop_domain_label"),
    )

    op.create_table(
        "field_mapping",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("schema_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ontology_schema.id", ondelete="CASCADE"), nullable=False),
        sa.Column("class_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ontology_class.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("data_source_table.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.UniqueConstraint("class_id", "table_id", name="uq_mapping_class_table"),
    )

    op.create_table(
        "field_mapping_binding",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("mapping_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("field_mapping.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_kind", sa.String(16), nullable=False),
        sa.Column("target_property_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ontology_property.id", ondelete="CASCADE")),
        sa.Column("source_column", sa.String(128), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.CheckConstraint("target_kind IN ('instance_uri','property')", name="ck_fmb_kind"),
    )

    op.create_table(
        "extraction_task",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("task_type", sa.String(24), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("schema_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ontology_schema.id", ondelete="SET NULL")),
        sa.Column("input", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("progress", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("output_summary", postgresql.JSONB()),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.CheckConstraint(
            "task_type IN ('schema_induction','instance_unstructured','instance_structured','business_logic')",
            name="ck_et_type",
        ),
        sa.CheckConstraint("status IN ('pending','running','succeeded','failed')", name="ck_et_status"),
    )

    op.create_table(
        "ontology_instance",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("schema_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ontology_schema.id", ondelete="CASCADE"), nullable=False),
        sa.Column("class_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ontology_class.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("local_name", sa.String(255)),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("source_ref", postgresql.JSONB()),
        sa.Column("confidence", sa.Numeric(5, 2)),
        sa.Column("extraction_task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("extraction_task.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.CheckConstraint(
            "source_type IN ('ai_unstructured','structured_mapping','manual')",
            name="ck_oi_source",
        ),
    )
    op.create_index("idx_instance_class", "ontology_instance", ["class_id"])

    op.create_table(
        "instance_data_value",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("instance_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ontology_instance.id", ondelete="CASCADE"), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ontology_property.id", ondelete="CASCADE"), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
    )
    op.create_index("idx_data_value_instance", "instance_data_value", ["instance_id"])

    op.create_table(
        "instance_relation",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("subject_instance_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ontology_instance.id", ondelete="CASCADE"), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ontology_property.id", ondelete="CASCADE"), nullable=False),
        sa.Column("object_instance_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ontology_instance.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
    )
    op.create_index("idx_relation_subject", "instance_relation", ["subject_instance_id"])

    op.create_table(
        "business_logic_rule",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("schema_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ontology_schema.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_type", sa.String(16), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("condition", postgresql.JSONB(), nullable=False),
        sa.Column("consequence", postgresql.JSONB()),
        sa.Column("action_required", sa.Text()),
        sa.Column("severity", sa.String(16)),
        sa.Column("source_doc_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("data_source_file.id")),
        sa.Column("extraction_task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("extraction_task.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.CheckConstraint("rule_type IN ('causality','constraint')", name="ck_blr_type"),
    )

    op.create_table(
        "graph_cache",
        sa.Column("schema_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ontology_schema.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("mode", sa.String(16), primary_key=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
    )


def downgrade() -> None:
    op.drop_table("graph_cache")
    op.drop_table("business_logic_rule")
    op.drop_index("idx_relation_subject", table_name="instance_relation")
    op.drop_table("instance_relation")
    op.drop_index("idx_data_value_instance", table_name="instance_data_value")
    op.drop_table("instance_data_value")
    op.drop_index("idx_instance_class", table_name="ontology_instance")
    op.drop_table("ontology_instance")
    op.drop_table("extraction_task")
    op.drop_table("field_mapping_binding")
    op.drop_table("field_mapping")
    op.drop_table("ontology_property")
    op.drop_table("ontology_class")
    op.drop_table("ontology_schema")
    op.drop_table("data_source_file")
    op.drop_table("data_source_table_column")
    op.drop_table("data_source_table")
    op.drop_table("data_source_db")
