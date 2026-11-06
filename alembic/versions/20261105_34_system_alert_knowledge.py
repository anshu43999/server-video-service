"""System AI knowledge releases and pinned project inheritance."""
from alembic import op
import sqlalchemy as sa

revision = "20261105_34"
down_revision = "20261104_33"
branch_labels = None
depends_on = None


def upgrade():
    catalog = op.create_table("system_knowledge_catalog", sa.Column("catalog_id", sa.Integer(), primary_key=True),
                              sa.Column("revision", sa.Integer(), nullable=False), sa.Column("payload", sa.JSON(), nullable=False))
    releases = op.create_table("system_knowledge_releases", sa.Column("version", sa.Integer(), primary_key=True), sa.Column("snapshot", sa.JSON(), nullable=False))
    bases = op.create_table("project_knowledge_bases",
                           sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.project_id", ondelete="RESTRICT"), primary_key=True),
                           sa.Column("version", sa.Integer(), sa.ForeignKey("system_knowledge_releases.version", ondelete="RESTRICT"), nullable=False),
                           sa.Column("revision", sa.Integer(), nullable=False))
    from app.system_alert_knowledge import initial_knowledge, initial_release
    payload = initial_knowledge()
    op.bulk_insert(catalog, [{"catalog_id": 1, "revision": 1, "payload": payload}])
    op.bulk_insert(releases, [{"version": 1, "snapshot": initial_release(payload)}])
    op.get_bind().execute(bases.insert().from_select(["project_id", "version", "revision"],
                         sa.select(sa.column("project_id"), sa.literal(1), sa.literal(1)).select_from(sa.table("projects"))))


def downgrade():
    bind = op.get_bind()
    releases = bind.execute(sa.text("SELECT count(*) FROM system_knowledge_releases")).scalar_one()
    if releases:
        raise RuntimeError("system knowledge downgrade refused: immutable releases and project bindings are durable")
    op.drop_table("project_knowledge_bases")
    op.drop_table("system_knowledge_releases")
    op.drop_table("system_knowledge_catalog")
