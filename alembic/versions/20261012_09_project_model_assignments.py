"""Pin project assignment parameters and stream model versions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261012_09"
down_revision = "20261010_08"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("project_model_assignments") as batch:
        batch.add_column(sa.Column("parameter_platform", sa.String(16), nullable=False, server_default="server"))
        batch.add_column(sa.Column("parameter_revision", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("parameter_snapshot", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False, server_default=sa.text("'{}'")))
        batch.create_check_constraint("ck_project_model_assignment_platform", "parameter_platform IN ('android', 'server')")
        batch.create_check_constraint("ck_project_model_assignment_parameter_revision", "parameter_revision >= 0")
    with op.batch_alter_table("stream_configs") as batch:
        batch.add_column(sa.Column("model_version", sa.String(128), nullable=True))
    # Historical assignments lack a reviewed snapshot. Retain metadata while
    # requiring explicit approval before runtime use.
    op.execute(sa.text("UPDATE project_model_assignments SET enabled = false WHERE parameter_snapshot = '{}'"))


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT COUNT(*) FROM project_model_assignments WHERE parameter_revision <> 0 OR parameter_snapshot <> '{}'" )).scalar_one():
        raise RuntimeError("model assignment downgrade refused: pinned parameters exist")
    if bind.execute(sa.text("SELECT COUNT(*) FROM stream_configs WHERE model_version IS NOT NULL")).scalar_one():
        raise RuntimeError("model assignment downgrade refused: pinned streams exist")
    with op.batch_alter_table("stream_configs") as batch:
        batch.drop_column("model_version")
    with op.batch_alter_table("project_model_assignments") as batch:
        batch.drop_constraint("ck_project_model_assignment_platform", type_="check")
        batch.drop_constraint("ck_project_model_assignment_parameter_revision", type_="check")
        batch.drop_column("parameter_snapshot")
        batch.drop_column("parameter_revision")
        batch.drop_column("parameter_platform")
