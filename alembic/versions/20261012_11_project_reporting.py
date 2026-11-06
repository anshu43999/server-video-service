"""Bounded project reports and audit keyset indexes."""
from alembic import op
import sqlalchemy as sa

revision = "20261012_11"
down_revision = "20261012_10"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_alert_events_project_created', 'alert_events', ['project_id', 'created_at'])
    op.create_index('ix_project_audit_page', 'project_audit_events', ['project_id', 'occurred_at', 'audit_id'])
    op.create_index('ix_platform_audit_page', 'platform_audit_events', ['occurred_at', 'audit_id'])
    if op.get_bind().dialect.name == 'sqlite':
        op.create_index('ix_project_audit_page_sqlite', 'project_audit_events', ['project_id', sa.text('julianday(occurred_at)'), 'audit_id'])
        op.create_index('ix_platform_audit_page_sqlite', 'platform_audit_events', [sa.text('julianday(occurred_at)'), 'audit_id'])


def downgrade():
    if op.get_bind().dialect.name == 'sqlite':
        op.drop_index('ix_platform_audit_page_sqlite', table_name='platform_audit_events')
        op.drop_index('ix_project_audit_page_sqlite', table_name='project_audit_events')
    op.drop_index('ix_platform_audit_page', table_name='platform_audit_events')
    op.drop_index('ix_project_audit_page', table_name='project_audit_events')
    op.drop_index('ix_alert_events_project_created', table_name='alert_events')
