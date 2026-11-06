"""Remove retired mobile legacy approval storage."""
from alembic import op

revision = "20261019_13"
down_revision = "20261014_12"
branch_labels = None
depends_on = None


def upgrade():
    for table in (
        "legacy_approval_rates",
        "legacy_approval_receipts",
        "legacy_approval_permits",
        "legacy_approval_idempotency",
        "legacy_approval_nonces",
        "legacy_approvals",
        "legacy_installation_challenges",
        "legacy_installations",
        "legacy_approval_service",
    ):
        op.drop_table(table)


def downgrade():
    raise RuntimeError("legacy approval storage was permanently removed; restore from a reviewed backup")
