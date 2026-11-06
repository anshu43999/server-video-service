"""Persist stable scene members and explicit v2 run plans.

The migration is additive. Existing scene rows receive deterministic legacy member
identities and inherit the scene input declaration; no run plans are inferred for
legacy scenes, so old multi-member configurations remain non-runnable.
"""
from hashlib import sha256
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261021_18"
down_revision = "20261020_17"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    document = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("project_scene_members")}
    if "member_id" not in columns:
        op.add_column("project_scene_members", sa.Column("member_id", sa.String(128), nullable=True))
    if "input_types" not in columns:
        op.add_column("project_scene_members", sa.Column("input_types", document, nullable=True))

    # Backfill only missing values. The digest is deterministic across restarts and
    # avoids position being used as a future member identity.
    rows = bind.execute(sa.text(
        "SELECT m.project_id, m.scene_id, m.position, m.model_id, m.model_version, m.target, "
        "m.input_types AS member_input_types, s.input_types AS scene_input_types "
        "FROM project_scene_members m JOIN project_scenes s "
        "ON s.project_id = m.project_id AND s.scene_id = m.scene_id"
    )).mappings().all()
    for row in rows:
        identity = "legacy-" + sha256("|".join(str(row[key]) for key in (
            "project_id", "scene_id", "position", "model_id", "model_version", "target"
        )).encode("utf-8")).hexdigest()[:32]
        input_types = row["member_input_types"]
        if isinstance(input_types, str):
            try:
                input_types = json.loads(input_types)
            except (TypeError, ValueError):
                input_types = None
        if not input_types:
            input_types = ["image", "video"]
            scene_types = row["scene_input_types"]
            if isinstance(scene_types, str):
                try:
                    scene_types = json.loads(scene_types)
                except (TypeError, ValueError):
                    scene_types = None
            if isinstance(scene_types, list) and scene_types:
                input_types = scene_types
        bind.execute(sa.text(
            "UPDATE project_scene_members SET member_id = COALESCE(member_id, :member_id), "
            "input_types = COALESCE(input_types, :input_types) "
            "WHERE project_id = :project_id AND scene_id = :scene_id AND position = :position"
        ), {"member_id": identity, "input_types": json.dumps(input_types),
            "project_id": row["project_id"], "scene_id": row["scene_id"], "position": row["position"]})

    # SQLite and PostgreSQL both support this batch operation; the guard prevents
    # null member identities from surviving an interrupted/backfilled migration.
    with op.batch_alter_table("project_scene_members") as batch:
        batch.alter_column("member_id", existing_type=sa.String(128), nullable=False)
        batch.alter_column("input_types", existing_type=document, nullable=False)
        names = {item["name"] for item in inspector.get_unique_constraints("project_scene_members")}
        if "uq_scene_member_release_target" in names:
            batch.drop_constraint("uq_scene_member_release_target", type_="unique")
        if "uq_scene_member_identity" not in names:
            batch.create_unique_constraint("uq_scene_member_identity", ["project_id", "scene_id", "member_id"])

    op.create_table(
        "project_scene_plans",
        sa.Column("project_id", sa.String(36), primary_key=True),
        sa.Column("scene_id", sa.String(128), primary_key=True),
        sa.Column("plan_id", sa.String(128), primary_key=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("input_types", document, nullable=False),
        sa.Column("execution", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("parameter_sources", document, nullable=True),
        sa.ForeignKeyConstraint(["project_id", "scene_id"], ["project_scenes.project_id", "project_scenes.scene_id"], ondelete="CASCADE", name="fk_scene_plans_project_scene"),
        sa.CheckConstraint("execution IN ('single', 'sync', 'async')", name="ck_scene_plan_execution"),
    )
    op.create_table(
        "project_scene_plan_members",
        sa.Column("project_id", sa.String(36), primary_key=True),
        sa.Column("scene_id", sa.String(128), primary_key=True),
        sa.Column("plan_id", sa.String(128), primary_key=True),
        sa.Column("member_id", sa.String(128), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "scene_id", "plan_id"], ["project_scene_plans.project_id", "project_scene_plans.scene_id", "project_scene_plans.plan_id"], ondelete="CASCADE", name="fk_scene_plan_members_plan"),
        sa.ForeignKeyConstraint(["project_id", "scene_id", "member_id"], ["project_scene_members.project_id", "project_scene_members.scene_id", "project_scene_members.member_id"], ondelete="CASCADE", name="fk_scene_plan_members_member"),
        sa.UniqueConstraint("project_id", "scene_id", "plan_id", "position", name="uq_scene_plan_member_position"),
        sa.CheckConstraint("position >= 0", name="ck_scene_plan_member_position"),
    )


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT COUNT(*) FROM project_scene_plans")).scalar_one():
        raise RuntimeError("scene suite downgrade refused: run plans exist")
    if bind.execute(sa.text("SELECT COUNT(*) FROM project_scene_plan_members")).scalar_one():
        raise RuntimeError("scene suite downgrade refused: plan members exist")
    op.drop_table("project_scene_plan_members")
    op.drop_table("project_scene_plans")
    if bind.execute(sa.text("SELECT COUNT(*) FROM project_scene_members")).scalar_one():
        raise RuntimeError("scene member downgrade refused: member identities exist")
    with op.batch_alter_table("project_scene_members") as batch:
        batch.drop_constraint("uq_scene_member_identity", type_="unique")
        batch.create_unique_constraint("uq_scene_member_release_target",
                                      ["project_id", "scene_id", "model_id", "model_version", "target"])
        batch.drop_column("input_types")
        batch.drop_column("member_id")
