"""Durable external APK jobs; retain the existing queue capacity and fencing."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261029_29"
down_revision = "20261029_28"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("app_apk_uploads", sa.Column("kind", sa.String(16), nullable=False, server_default="upload"))
    op.add_column("app_apk_uploads", sa.Column("external_url", sa.Text()))
    op.add_column("app_apk_uploads", sa.Column("external_hosts", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False, server_default="[]"))
    op.add_column("app_apk_uploads", sa.Column("fetch_evidence", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False, server_default="{}"))
    with op.batch_alter_table("app_apk_uploads") as batch:
        batch.add_column(sa.Column("target_artifact_id", sa.String(128)))
        batch.create_foreign_key("fk_app_external_target", "app_artifacts", ["target_artifact_id"], ["artifact_id"], ondelete="RESTRICT")
        batch.create_check_constraint("ck_app_upload_kind", "kind IN ('upload', 'external') AND (kind != 'external' OR external_url IS NOT NULL)")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM app_apk_uploads WHERE kind = 'external' LIMIT 1")).first():
        raise RuntimeError("external APK downgrade refused: durable history exists")
    with op.batch_alter_table("app_apk_uploads") as batch:
        batch.drop_constraint("fk_app_external_target", type_="foreignkey")
        batch.drop_constraint("ck_app_upload_kind", type_="check")
        for column in ("target_artifact_id", "fetch_evidence", "external_hosts", "external_url", "kind"):
            batch.drop_column(column)
