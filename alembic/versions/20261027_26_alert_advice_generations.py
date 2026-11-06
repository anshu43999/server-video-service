"""Persist immutable user-triggered alert-advice generations (M41-T05)."""
from alembic import op
import sqlalchemy as sa


revision = "20261027_26"
down_revision = "20261027_25"
branch_labels = None
depends_on = None


def upgrade():
    document = sa.JSON().with_variant(
        __import__("sqlalchemy.dialects.postgresql", fromlist=["JSONB"]).JSONB(), "postgresql"
    )
    op.create_table(
        "alert_advice_generations",
        sa.Column("project_id", sa.String(36), primary_key=True),
        sa.Column("generation_id", sa.String(128), primary_key=True),
        sa.Column("event_id", sa.String(255), nullable=False),
        sa.Column("requested_by", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(36), nullable=False),
        sa.Column("retry_of_generation_id", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("snapshot", document, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["project_id", "event_id"], ["alert_events.project_id", "alert_events.event_id"],
            ondelete="RESTRICT", name="fk_alert_advice_generation_event",
        ),
        sa.UniqueConstraint(
            "project_id", "event_id", "idempotency_key",
            name="uq_alert_advice_generation_idempotency",
        ),
        sa.CheckConstraint(
            "status IN ('GENERATED', 'NO_MATCH', 'PARTIAL', 'FAILED_RETRIEVAL', 'FAILED_GENERATION')",
            name="ck_alert_advice_generation_status",
        ),
    )
    op.create_index(
        "ix_alert_advice_generation_project_event_created", "alert_advice_generations",
        ["project_id", "event_id", "created_at"],
    )


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM alert_advice_generations LIMIT 1")).first():
        raise RuntimeError("alert advice generation downgrade refused: durable history exists")
    op.drop_table("alert_advice_generations")
