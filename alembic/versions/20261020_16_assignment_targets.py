"""Allow independent project model approvals for PC and mobile.

Existing rows, snapshots and revisions are preserved verbatim. No second target
is granted by migration. Downgrade refuses any scenario with two deployments.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261020_16"
down_revision = "20261019_15"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("project_model_assignments") as batch:
        batch.drop_constraint("uq_project_model_assignments_project_scenario", type_="unique")
        batch.create_unique_constraint("uq_project_model_assignments_project_scenario_platform",
                                       ["project_id", "scenario", "parameter_platform"])


def downgrade():
    duplicate = op.get_bind().execute(sa.text(
        "SELECT 1 FROM project_model_assignments GROUP BY project_id, scenario "
        "HAVING COUNT(*) > 1 LIMIT 1")).first()
    if duplicate:
        raise RuntimeError("assignment downgrade refused: dual-target deployments exist")
    with op.batch_alter_table("project_model_assignments") as batch:
        batch.drop_constraint("uq_project_model_assignments_project_scenario_platform", type_="unique")
        batch.create_unique_constraint("uq_project_model_assignments_project_scenario", ["project_id", "scenario"])
