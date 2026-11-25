"""Private, explicitly approved mobile alert videos; no public download route."""
from alembic import op
import sqlalchemy as sa
revision = '20261121_36'
down_revision = '20261117_35'
branch_labels = depends_on = None


def upgrade():
    op.create_table('mobile_alert_clips', sa.Column('project_id', sa.String(36), primary_key=True),
        sa.Column('event_id', sa.String(255), primary_key=True), sa.Column('account_id', sa.String(36), primary_key=True),
        sa.Column('sha256', sa.String(64), primary_key=True), sa.Column('receipt_id', sa.String(36), nullable=False, unique=True),
        sa.Column('received_ms', sa.BigInteger(), nullable=False), sa.Column('content', sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(['project_id','event_id'], ['alert_events.project_id','alert_events.event_id'], ondelete='CASCADE'))


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT COUNT(*) FROM mobile_alert_clips')):
        raise RuntimeError('cannot downgrade while confirmed clips and receipts are retained')
    op.drop_table('mobile_alert_clips')
