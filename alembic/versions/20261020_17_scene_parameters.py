"""Freeze reviewed scene parameters; never backfill authority for old scenes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261020_17"
down_revision = "20261020_16"
branch_labels = None
depends_on = None


def upgrade():
    document = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.add_column("project_scene_members", sa.Column("parameter_snapshot", document, nullable=True))


def downgrade():
    # JSON null is distinct from SQL NULL on both supported databases.
    if op.get_bind().execute(sa.text(
        "SELECT COUNT(*) FROM project_scene_members "
        "WHERE parameter_snapshot IS NOT NULL AND CAST(parameter_snapshot AS TEXT) != 'null'"
    )).scalar_one():
        raise RuntimeError("scene parameter downgrade refused: reviewed snapshots exist")
    with op.batch_alter_table("project_scene_members") as batch:
        batch.drop_column("parameter_snapshot")
