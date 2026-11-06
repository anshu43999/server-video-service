"""Durable installation proof and explicit mobile legacy ownership approval."""
from uuid import uuid4
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20261014_12'
down_revision = '20261012_11'
branch_labels = None
depends_on = None


def upgrade():
    # Forward repair of old SQLite BIGINT primary keys: only INTEGER PRIMARY
    # KEY auto-generates rowids. PostgreSQL retains its BIGINT sequences.
    if op.get_bind().dialect.name == 'sqlite':
        for table, column in (('alert_disposition_actions', 'id'), ('alert_rule_audits', 'id'),
                              ('model_parameter_audits', 'id'), ('false_positive_feedback', 'action_id')):
            with op.batch_alter_table(table) as batch:
                batch.alter_column(column, existing_type=sa.BigInteger(), type_=sa.Integer(), existing_nullable=False)
    doc = sa.JSON().with_variant(postgresql.JSONB(), 'postgresql')
    op.create_table('legacy_approval_service',
        sa.Column('singleton', sa.Integer, primary_key=True),
        sa.Column('instance_id', sa.String(36), nullable=False, unique=True),
        sa.Column('origin', sa.String(512), nullable=True),
        sa.CheckConstraint('singleton = 1', name='ck_legacy_service_singleton'))
    op.execute(sa.text('INSERT INTO legacy_approval_service (singleton, instance_id) VALUES (1, :id)').bindparams(id=str(uuid4())))
    op.create_table('legacy_installations',
        sa.Column('installation_id', sa.String(36), primary_key=True),
        sa.Column('account_id', sa.String(36), sa.ForeignKey('accounts.account_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('instance_id', sa.String(36), nullable=False),
        sa.Column('dataset_id', sa.String(36), nullable=False, unique=True),
        sa.Column('key_thumbprint', sa.String(64), nullable=False, unique=True),
        sa.Column('public_key', sa.Text, nullable=False),
        sa.Column('active', sa.Boolean, nullable=False),
        sa.Column('revision', sa.Integer, nullable=False),
        sa.Column('generation', sa.Integer, nullable=False),
        sa.Column('operation_id', sa.String(36), nullable=True, unique=True),
        sa.CheckConstraint('revision >= 1 AND generation >= 0', name='ck_legacy_install_revision'))
    op.create_table('legacy_installation_challenges',
        sa.Column('challenge_id', sa.String(36), primary_key=True),
        sa.Column('account_id', sa.String(36), sa.ForeignKey('accounts.account_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('key_thumbprint', sa.String(64), nullable=False),
        sa.Column('challenge', sa.String(64), nullable=False),
        sa.Column('expires_at', sa.BigInteger, nullable=False),
        sa.Column('consumed', sa.Boolean, nullable=False))
    op.create_table('legacy_approvals',
        sa.Column('approval_id', sa.String(36), primary_key=True),
        sa.Column('installation_id', sa.String(36), sa.ForeignKey('legacy_installations.installation_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('account_id', sa.String(36), sa.ForeignKey('accounts.account_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('state', sa.String(32), nullable=False),
        sa.Column('revision', sa.Integer, nullable=False),
        sa.Column('generation', sa.Integer, nullable=False),
        sa.Column('operation_id', sa.String(36), nullable=True, unique=True),
        sa.Column('review_expires_at', sa.BigInteger, nullable=False),
        sa.Column('approval_expires_at', sa.BigInteger, nullable=True),
        sa.Column('lease_expires_at', sa.BigInteger, nullable=True),
        sa.Column('payload', doc, nullable=False),
        sa.UniqueConstraint('installation_id', 'generation', name='uq_legacy_install_generation'),
        sa.CheckConstraint('revision >= 1 AND generation >= 1', name='ck_legacy_approval_revision'),
        sa.CheckConstraint("state IN ('PENDING_REVIEW','APPROVED','EXECUTING','RECONCILIATION_REQUIRED','COMPLETED','REJECTED','EXPIRED','REVOKED')", name='ck_legacy_approval_state'))
    for column in ('installation_id', 'account_id', 'state'):
        op.create_index('ix_legacy_approvals_' + column, 'legacy_approvals', [column])
    op.create_table('legacy_approval_nonces',
        sa.Column('installation_id', sa.String(36), sa.ForeignKey('legacy_installations.installation_id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('nonce_digest', sa.String(64), primary_key=True),
        sa.Column('expires_at', sa.BigInteger, nullable=False))
    op.create_table('legacy_approval_idempotency',
        sa.Column('account_id', sa.String(36), sa.ForeignKey('accounts.account_id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('action', sa.String(32), primary_key=True),
        sa.Column('resource_id', sa.String(36), primary_key=True),
        sa.Column('idempotency_key', sa.String(128), primary_key=True),
        sa.Column('body_digest', sa.String(64), nullable=False),
        sa.Column('result_id', sa.String(36), nullable=False))
    op.create_table('legacy_approval_permits',
        sa.Column('permit_id', sa.String(36), primary_key=True),
        sa.Column('approval_id', sa.String(36), sa.ForeignKey('legacy_approvals.approval_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('revision', sa.Integer, nullable=False),
        sa.Column('phase', sa.String(16), nullable=False),
        sa.Column('expires_at', sa.BigInteger, nullable=False))
    op.create_table('legacy_approval_receipts',
        sa.Column('receipt_id', sa.String(36), primary_key=True),
        sa.Column('approval_id', sa.String(36), sa.ForeignKey('legacy_approvals.approval_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('result_digest', sa.String(64), nullable=False),
        sa.Column('observation_digest', sa.String(64), nullable=False),
        sa.Column('payload', doc, nullable=False),
        sa.UniqueConstraint('approval_id', 'observation_digest', name='uq_legacy_receipt_result'))
    op.create_table('legacy_approval_rates',
        sa.Column('subject', sa.String(64), primary_key=True),
        sa.Column('bucket', sa.String(32), primary_key=True),
        sa.Column('window', sa.BigInteger, nullable=False),
        sa.Column('count', sa.Integer, nullable=False))


def downgrade():
    bind = op.get_bind()
    # Approval history is not disposable, even when all requests were rejected.
    if bind.execute(sa.text('SELECT COUNT(*) FROM legacy_installations')).scalar_one():
        raise RuntimeError('legacy approval downgrade refused: installation history exists; reviewed backup restore required')
    for table in ('legacy_approval_rates', 'legacy_approval_receipts', 'legacy_approval_permits',
                  'legacy_approval_idempotency', 'legacy_approval_nonces', 'legacy_approvals',
                  'legacy_installation_challenges', 'legacy_installations', 'legacy_approval_service'):
        op.drop_table(table)
    if bind.dialect.name == 'sqlite':
        for table, column in (('alert_disposition_actions', 'id'), ('alert_rule_audits', 'id'),
                              ('model_parameter_audits', 'id'), ('false_positive_feedback', 'action_id')):
            with op.batch_alter_table(table) as batch:
                batch.alter_column(column, existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=False)
