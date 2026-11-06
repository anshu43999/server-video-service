"""Persist versioned simulated alert-advice knowledge (M41-T02)."""
from alembic import op
import sqlalchemy as sa


revision = "20261027_25"
down_revision = "20261026_24"
branch_labels = None
depends_on = None


def upgrade():
    document = sa.JSON().with_variant(
        __import__("sqlalchemy.dialects.postgresql", fromlist=["JSONB"]).JSONB(), "postgresql"
    )
    op.create_table(
        "alert_advice_knowledge_entries",
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.project_id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("entry_id", sa.String(128), primary_key=True),
        sa.Column("alert_type_id", sa.String(128), nullable=False),
        sa.Column("recognition_category_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("payload", document, nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="ck_alert_advice_knowledge_status"),
        sa.UniqueConstraint(
            "project_id", "alert_type_id", "recognition_category_id",
            name="uq_alert_advice_knowledge_match_key",
        ),
    )
    op.create_index("ix_alert_advice_knowledge_project_status", "alert_advice_knowledge_entries", ["project_id", "status"])
    op.create_index(
        "ix_alert_advice_knowledge_project_match", "alert_advice_knowledge_entries",
        ["project_id", "alert_type_id", "recognition_category_id"],
    )
    op.create_table(
        "alert_advice_knowledge_revisions",
        sa.Column("project_id", sa.String(36), primary_key=True),
        sa.Column("entry_id", sa.String(128), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("snapshot", document, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["project_id", "entry_id"],
            ["alert_advice_knowledge_entries.project_id", "alert_advice_knowledge_entries.entry_id"],
            ondelete="RESTRICT", name="fk_alert_advice_revision_entry",
        ),
        sa.CheckConstraint(
            "action IN ('CREATE', 'UPDATE', 'ACTIVATE', 'DEACTIVATE')",
            name="ck_alert_advice_revision_action",
        ),
    )
    op.create_index(
        "ix_alert_advice_revisions_project_entry", "alert_advice_knowledge_revisions",
        ["project_id", "entry_id", "revision"],
    )


def downgrade():
    connection = op.get_bind()
    for table in ("alert_advice_knowledge_revisions", "alert_advice_knowledge_entries"):
        if connection.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("alert advice knowledge downgrade refused: durable knowledge exists")
    op.drop_table("alert_advice_knowledge_revisions")
    op.drop_table("alert_advice_knowledge_entries")
