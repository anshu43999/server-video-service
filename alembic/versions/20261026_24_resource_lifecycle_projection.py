"""M112 lifecycle inventory/facts use the existing M111 sequence and receipts."""
from alembic import op
import sqlalchemy as sa

revision = '20261026_24'
down_revision = '20261025_23'
branch_labels = None
depends_on = None


def upgrade():
    document = sa.JSON().with_variant(__import__('sqlalchemy.dialects.postgresql', fromlist=['JSONB']).JSONB(), 'postgresql')
    with op.batch_alter_table('model_update_devices') as batch:
        batch.add_column(sa.Column('lifecycle_facts', document, nullable=False, server_default=sa.text("'{}'")))
        batch.add_column(sa.Column('lifecycle_inventory', document, nullable=False, server_default=sa.text("'[]'")))
    with op.batch_alter_table('model_update_snapshots') as batch:
        batch.add_column(sa.Column('lifecycle_payload', document, nullable=False, server_default=sa.text("'[]'")))
    for table in ('model_update_changes', 'model_update_reports'):
        with op.batch_alter_table(table) as batch:
            batch.alter_column('update_id', existing_type=sa.String(128), nullable=True)


def downgrade():
    bind = op.get_bind()
    for table in ('model_update_installations', 'model_update_changes', 'model_update_reports'):
        if bind.execute(sa.text('SELECT 1 FROM ' + table + ' LIMIT 1')).first():
            raise RuntimeError('durable facts prevent lifecycle downgrade')
    for table in ('model_update_changes', 'model_update_reports'):
        with op.batch_alter_table(table) as batch:
            batch.alter_column('update_id', existing_type=sa.String(128), nullable=False)
    with op.batch_alter_table('model_update_devices') as batch:
        batch.drop_column('lifecycle_inventory')
        batch.drop_column('lifecycle_facts')
    with op.batch_alter_table('model_update_snapshots') as batch:
        batch.drop_column('lifecycle_payload')
