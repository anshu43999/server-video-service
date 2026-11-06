"""Add complete ordered plan snapshots without rewriting M36-T19 history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261022_21"
down_revision = "20261021_20"
branch_labels = None
depends_on = None


def upgrade():
    # Member rows are replaced during scene approval/edit. Keep consumed tokens
    # for replay protection and permit idempotent stop of an old revision.
    with op.batch_alter_table("project_scene_runtime_grants") as batch:
        batch.drop_constraint("fk_scene_runtime_grants_scene_member", type_="foreignkey")
    document = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.add_column("project_scene_runtime_grants", sa.Column(
        "execution_mode", sa.String(16), nullable=False, server_default="single"))
    op.add_column("project_scene_runtime_grants", sa.Column(
        "member_snapshot", document, nullable=False, server_default="[]"))
    op.add_column("project_scene_runtime_grants", sa.Column(
        "authority_snapshot", document, nullable=False, server_default="{}"))
    op.add_column("project_scene_runtime_grants", sa.Column(
        "request_digest", sa.String(64), nullable=True))
    op.create_index("uq_scene_runtime_grant_request", "project_scene_runtime_grants",
                    ["request_digest"], unique=True)
    # Old tokens cannot prove the authority generation. Keep their history but
    # require a fresh start after upgrade; the single-member API stays compatible.
    op.execute(sa.text("UPDATE project_scene_runtime_grants SET revoked_at = CURRENT_TIMESTAMP "
                       "WHERE revoked_at IS NULL"))


def downgrade():
    # Never silently discard snapshot identity or request replay protection.
    if op.get_bind().execute(sa.text(
            "SELECT COUNT(*) FROM project_scene_runtime_grants")).scalar_one():
        raise RuntimeError("composite runtime grant downgrade refused: grant records exist")
    op.drop_index("uq_scene_runtime_grant_request", table_name="project_scene_runtime_grants")
    op.drop_column("project_scene_runtime_grants", "request_digest")
    op.drop_column("project_scene_runtime_grants", "member_snapshot")
    op.drop_column("project_scene_runtime_grants", "authority_snapshot")
    op.drop_column("project_scene_runtime_grants", "execution_mode")
    with op.batch_alter_table("project_scene_runtime_grants") as batch:
        batch.create_foreign_key("fk_scene_runtime_grants_scene_member", "project_scene_members",
            ["project_id", "scene_id", "member_id"], ["project_id", "scene_id", "member_id"], ondelete="CASCADE")
