"""Persist project delivery policies without platform provider credentials."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261010_08"
down_revision = "20261010_07"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("model_parameter_profiles") as batch:
        batch.add_column(sa.Column("scope", sa.String(16), nullable=False, server_default="PLATFORM"))
        batch.drop_constraint("uq_model_parameter_profile", type_="unique")
        batch.create_check_constraint("ck_model_parameter_profiles_scope", "scope IN ('PLATFORM', 'PROJECT')")
        batch.create_unique_constraint("uq_model_parameter_profile", ["project_id", "scope", "model_id", "model_version", "platform"])
    op.execute(sa.text("UPDATE model_parameter_profiles SET scope = 'PROJECT' WHERE project_id <> '00000000-0000-0000-0000-000000000001'"))
    op.create_table(
        "project_business_config",
        sa.Column("project_id", sa.String(36), primary_key=True),
        sa.Column("config_key", sa.String(64), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="RESTRICT"),
        sa.CheckConstraint("revision >= 1", name="ck_project_business_config_revision"),
    )


def downgrade():
    count = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM project_business_config")).scalar_one()
    if count:
        raise RuntimeError("business configuration downgrade refused: back up project policies first")
    profiles = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM model_parameter_profiles WHERE scope = 'PROJECT'")).scalar_one()
    if profiles:
        raise RuntimeError("business configuration downgrade refused: project parameter overrides exist")
    op.drop_table("project_business_config")
    with op.batch_alter_table("model_parameter_profiles") as batch:
        batch.drop_constraint("ck_model_parameter_profiles_scope", type_="check")
        batch.drop_constraint("uq_model_parameter_profile", type_="unique")
        batch.create_unique_constraint("uq_model_parameter_profile", ["project_id", "model_id", "model_version", "platform"])
        batch.drop_column("scope")
