"""Durable mobile model update control plane (M111-T02)."""
from alembic import op
import sqlalchemy as sa

revision = '20261025_23'
down_revision = '20261025_22'
branch_labels = None
depends_on = None


def upgrade():
    # Copy the frozen v23 DDL, not future application metadata.
    document = sa.JSON().with_variant(__import__('sqlalchemy.dialects.postgresql', fromlist=['JSONB']).JSONB(), 'postgresql')
    def col(name, typ, **kw):
        return sa.Column(name, typ, **kw)
    op.create_table('model_update_installations', col('installation_id', sa.String(128), primary_key=True),
                    col('epoch', sa.BigInteger(), nullable=False), col('device_id', sa.String(128)))
    op.create_table('model_update_devices', col('device_id', sa.String(128), primary_key=True),
        sa.Column('installation_id', sa.String(128), sa.ForeignKey('model_update_installations.installation_id'), nullable=False),
        col('account_id', sa.String(128), nullable=False, index=True), col('origin', sa.String(256), nullable=False),
        col('epoch', sa.BigInteger(), nullable=False), col('revoked', sa.Boolean(), nullable=False),
        col('capabilities', document, nullable=False), col('push_provider', sa.String(16), nullable=False),
        col('push_token', sa.String(4096)), col('token_generation', sa.BigInteger(), nullable=False),
        col('notification_permission', sa.String(32), nullable=False),
        col('inventory_revision', sa.BigInteger(), nullable=False), col('inventory_digest', sa.String(64)),
        col('inventory', document, nullable=False), col('source_epochs', document, nullable=False),
        col('sequence', sa.BigInteger(), nullable=False),
        col('cursor_floor', sa.BigInteger(), nullable=False),
        col('last_contact', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('installation_id', 'epoch'))
    def device_pk():
        return sa.Column('device_id', sa.String(128), sa.ForeignKey('model_update_devices.device_id'), primary_key=True)
    def stamp():
        return col('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    op.create_table('model_update_targets', col('update_id', sa.String(128), primary_key=True),
        col('source_key', sa.String(512), nullable=False, index=True), col('payload', document, nullable=False))
    op.create_table('model_update_inbox', device_pk(), col('update_id', sa.String(128), primary_key=True),
        col('project_id', sa.String(128), nullable=False, index=True), col('source_key', sa.String(512), nullable=False),
        col('is_current', sa.Boolean(), nullable=False, index=True),
        col('payload', document, nullable=False), col('report_seq', sa.BigInteger(), nullable=False),
        col('authority_revision', sa.BigInteger(), nullable=False),
        col('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table('model_update_changes', device_pk(), col('sequence', sa.BigInteger(), primary_key=True),
        col('update_id', sa.String(128), nullable=False), col('payload', document, nullable=False), stamp())
    op.create_table('model_update_reports', device_pk(), col('event_id', sa.String(128), primary_key=True),
        col('update_id', sa.String(128), nullable=False), col('payload_digest', sa.String(64), nullable=False),
        col('payload', document, nullable=False), col('result', document, nullable=False), stamp())
    op.create_table('model_update_tickets', col('token_digest', sa.String(64), primary_key=True),
        sa.Column('device_id', sa.String(128), sa.ForeignKey('model_update_devices.device_id'), nullable=True, index=True),
        col('kind', sa.String(32), nullable=False), col('payload', document, nullable=False),
        col('expires_at', sa.DateTime(timezone=True), nullable=False, index=True))
    op.create_table('model_update_snapshots', col('snapshot_id', sa.String(128), primary_key=True),
        sa.Column('device_id', sa.String(128), sa.ForeignKey('model_update_devices.device_id'), nullable=False, index=True),
        col('sequence', sa.BigInteger(), nullable=False), col('payload', document, nullable=False),
        col('cursor', sa.String(2048), nullable=False), col('expires_at', sa.DateTime(timezone=True), nullable=False, index=True))
    op.create_table('model_update_push_outbox', device_pk(), col('dirty_sequence', sa.BigInteger(), nullable=False),
        col('sent_sequence', sa.BigInteger(), nullable=False), col('lease_sequence', sa.BigInteger(), nullable=False),
        col('lease_id', sa.String(128)), col('lease_until', sa.DateTime(timezone=True)),
        col('next_attempt', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        col('attempts', sa.Integer(), nullable=False), col('disabled_reason', sa.String(64)),
        col('dirty_since', sa.DateTime(timezone=True)))
    op.create_table('model_update_domain_outbox', col('event_id', sa.String(128), primary_key=True),
        col('project_id', sa.String(128), nullable=False, index=True), col('payload', document, nullable=False),
        stamp(), col('processed_at', sa.DateTime(timezone=True)))
    op.create_table('model_update_rate_buckets', col('bucket_key', sa.String(256), primary_key=True),
        col('tokens', sa.BigInteger(), nullable=False), col('updated_micros', sa.BigInteger(), nullable=False))
    op.create_table('model_update_metrics', col('metric_key', sa.String(128), primary_key=True),
        col('count', sa.BigInteger(), nullable=False), col('total', sa.Float(), nullable=False),
        col('maximum', sa.Float(), nullable=False))


def downgrade():
    connection = op.get_bind()
    tables = ('model_update_reports', 'model_update_changes', 'model_update_inbox', 'model_update_push_outbox',
              'model_update_snapshots', 'model_update_tickets', 'model_update_domain_outbox',
              'model_update_targets', 'model_update_devices', 'model_update_installations', 'model_update_rate_buckets',
              'model_update_metrics')
    for name in tables:
        if connection.execute(sa.text(f'SELECT COUNT(*) FROM {name}')).scalar_one():
            raise RuntimeError('model update downgrade refused: durable facts exist')
    for name in tables:
        op.drop_table(name)
