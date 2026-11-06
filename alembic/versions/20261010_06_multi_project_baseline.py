"""Establish the multi-project identity and ownership baseline.

Revision ID: 20261010_06
Revises: 20260920_05
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import UUID, uuid5

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261010_06"
down_revision: Union[str, None] = "20260920_05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_PROJECT_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_PROJECT_CODE = "legacy-default"
IDENTITY_NAMESPACE = UUID("b31965a3-7fc1-4ae9-b1c1-cf2edbd74d45")

NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ix": "ix_%(column_0_label)s",
}

PROJECT_OWNED_TABLES = (
    "alert_events",
    "alert_disposition_actions",
    "false_positive_feedback",
    "alert_rules",
    "alert_rule_bindings",
    "alert_rule_audits",
    "model_parameter_profiles",
    "model_parameter_audits",
    "alert_verification_config",
    "alert_verifications",
    "alert_delivery_receipts",
    "stream_configs",
)

PROJECT_PRIMARY_KEYS = {
    "alert_events": ("event_id",),
    "false_positive_feedback": ("entry_id",),
    "alert_rules": ("rule_id",),
    "alert_rule_bindings": ("rule_id", "source_id"),
    "model_parameter_profiles": ("profile_key",),
    "alert_verification_config": ("config_key",),
    "alert_verifications": ("event_id",),
    "alert_delivery_receipts": ("delivery_id",),
    "stream_configs": ("stream_id",),
}

PROJECT_UNIQUES = {
    "alert_events": (("uq_alert_events_project_event", ("project_id", "event_id")),),
    "false_positive_feedback": (
        ("uq_false_positive_feedback_project_entry", ("project_id", "entry_id")),
        ("uq_false_positive_feedback_project_action", ("project_id", "action_id")),
    ),
    "alert_rules": (("uq_alert_rules_project_rule", ("project_id", "rule_id")),),
    "model_parameter_profiles": (
        ("uq_model_parameter_profiles_project_key", ("project_id", "profile_key")),
        ("uq_model_parameter_profile", ("project_id", "model_id", "model_version", "platform")),
    ),
    "alert_verification_config": (
        ("uq_alert_verification_config_project_key", ("project_id", "config_key")),
    ),
    "alert_verifications": (
        ("uq_alert_verifications_project_event", ("project_id", "event_id")),
    ),
    "alert_delivery_receipts": (
        ("uq_alert_delivery_receipts_project_delivery", ("project_id", "delivery_id")),
    ),
    "stream_configs": (("uq_stream_configs_project_stream", ("project_id", "stream_id")),),
}

OLD_FOREIGN_KEYS = (
    ("alert_disposition_actions", ("event_id",), "alert_events", "CASCADE"),
    ("false_positive_feedback", ("event_id",), "alert_events", "CASCADE"),
    ("false_positive_feedback", ("action_id",), "alert_disposition_actions", "CASCADE"),
    ("alert_rule_bindings", ("rule_id",), "alert_rules", "CASCADE"),
    ("model_parameter_audits", ("profile_key",), "model_parameter_profiles", "CASCADE"),
    ("alert_verifications", ("event_id",), "alert_events", "CASCADE"),
)

PROJECT_FOREIGN_KEYS = (
    (
        "alert_disposition_actions",
        "fk_alert_disposition_actions_project_event",
        ("project_id", "event_id"),
        "alert_events",
        ("project_id", "event_id"),
        "CASCADE",
    ),
    (
        "false_positive_feedback",
        "fk_false_positive_feedback_project_event",
        ("project_id", "event_id"),
        "alert_events",
        ("project_id", "event_id"),
        "CASCADE",
    ),
    (
        "false_positive_feedback",
        "fk_false_positive_feedback_project_action",
        ("project_id", "action_id"),
        "alert_disposition_actions",
        ("project_id", "id"),
        "CASCADE",
    ),
    (
        "alert_rule_bindings",
        "fk_alert_rule_bindings_project_rule",
        ("project_id", "rule_id"),
        "alert_rules",
        ("project_id", "rule_id"),
        "CASCADE",
    ),
    (
        "model_parameter_audits",
        "fk_model_parameter_audits_project_profile",
        ("project_id", "profile_key"),
        "model_parameter_profiles",
        ("project_id", "profile_key"),
        "CASCADE",
    ),
    (
        "alert_verifications",
        "fk_alert_verifications_project_event",
        ("project_id", "event_id"),
        "alert_events",
        ("project_id", "event_id"),
        "CASCADE",
    ),
    (
        "alert_delivery_receipts",
        "fk_alert_delivery_receipts_project_event",
        ("project_id", "event_id"),
        "alert_events",
        ("project_id", "event_id"),
        "RESTRICT",
    ),
)


def _json_document():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _inspector():
    return sa.inspect(op.get_bind())


def _recreate_mode() -> str:
    return "always" if op.get_bind().dialect.name == "sqlite" else "auto"


def _pk_name(table_name: str) -> str:
    return _inspector().get_pk_constraint(table_name).get("name") or f"pk_{table_name}"


def _fk_name(table_name: str, columns: tuple[str, ...], referred_table: str) -> str:
    for item in _inspector().get_foreign_keys(table_name):
        if tuple(item.get("constrained_columns") or ()) == columns and item.get("referred_table") == referred_table:
            return item.get("name") or f"fk_{table_name}_{columns[0]}_{referred_table}"
    raise RuntimeError(f"missing foreign key on {table_name}({', '.join(columns)})")


def _unique_name(table_name: str, columns: tuple[str, ...]) -> str:
    for item in _inspector().get_unique_constraints(table_name):
        if tuple(item.get("column_names") or ()) == columns:
            return item.get("name") or f"uq_{table_name}_{columns[0]}"
    raise RuntimeError(f"missing unique constraint on {table_name}({', '.join(columns)})")


def _assert_no_nulls(table_name: str, column_name: str) -> None:
    value = op.get_bind().execute(
        sa.text(f'SELECT COUNT(*) FROM "{table_name}" WHERE "{column_name}" IS NULL')
    ).scalar_one()
    if int(value):
        raise RuntimeError(f"cannot complete multi-project migration: {table_name}.{column_name} has null rows")


def _deterministic_account_id(username: str) -> str:
    return str(uuid5(IDENTITY_NAMESPACE, f"legacy-account:{username}"))


def _validate_legacy_owner() -> None:
    bind = op.get_bind()
    account_count = int(bind.execute(sa.text("SELECT COUNT(*) FROM accounts")).scalar_one())
    enabled_admin_count = int(bind.execute(
        sa.text("SELECT COUNT(*) FROM accounts WHERE role = 'admin' AND enabled = :enabled"),
        {"enabled": True},
    ).scalar_one())
    if account_count and not enabled_admin_count:
        raise RuntimeError(
            "cannot create the default project: legacy accounts exist but no enabled administrator owner was found"
        )


def _add_identity_columns() -> None:
    op.add_column("accounts", sa.Column("account_id", sa.String(36), nullable=True))
    op.add_column("accounts", sa.Column("platform_role", sa.String(32), nullable=True))
    bind = op.get_bind()
    accounts = bind.execute(sa.text("SELECT username, role FROM accounts ORDER BY username")).mappings().all()
    for account in accounts:
        bind.execute(
            sa.text(
                "UPDATE accounts SET account_id = :account_id, platform_role = :platform_role "
                "WHERE username = :username"
            ),
            {
                "account_id": _deterministic_account_id(str(account["username"])),
                "platform_role": "PLATFORM_ADMIN" if account["role"] == "admin" else "NORMAL_USER",
                "username": account["username"],
            },
        )
    _assert_no_nulls("accounts", "account_id")
    _assert_no_nulls("accounts", "platform_role")
    with op.batch_alter_table("accounts", recreate=_recreate_mode(), naming_convention=NAMING_CONVENTION) as batch:
        batch.alter_column("account_id", existing_type=sa.String(36), nullable=False)
        batch.alter_column("platform_role", existing_type=sa.String(32), nullable=False)
        batch.create_check_constraint(
            "ck_accounts_platform_role", "platform_role IN ('PLATFORM_ADMIN', 'NORMAL_USER')"
        )
        batch.create_index("ix_accounts_platform_role", ["platform_role"])

    op.add_column("account_sessions", sa.Column("account_id", sa.String(36), nullable=True))
    bind.execute(
        sa.text(
            "UPDATE account_sessions SET account_id = "
            "(SELECT accounts.account_id FROM accounts WHERE accounts.username = account_sessions.username)"
        )
    )
    _assert_no_nulls("account_sessions", "account_id")
    username_foreign_key = _fk_name("account_sessions", ("username",), "accounts")
    with op.batch_alter_table("account_sessions", recreate=_recreate_mode(), naming_convention=NAMING_CONVENTION) as batch:
        batch.alter_column("account_id", existing_type=sa.String(36), nullable=False)
        batch.drop_constraint(username_foreign_key, type_="foreignkey")
        batch.create_index("ix_account_sessions_account_id", ["account_id"])

    account_primary_key = _pk_name("accounts")
    with op.batch_alter_table("accounts", recreate=_recreate_mode(), naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint(account_primary_key, type_="primary")
        batch.create_primary_key("pk_accounts", ["account_id"])
        batch.create_unique_constraint("uq_accounts_username", ["username"])

    with op.batch_alter_table("account_sessions", recreate=_recreate_mode(), naming_convention=NAMING_CONVENTION) as batch:
        batch.create_foreign_key(
            "fk_account_sessions_account_id_accounts",
            "accounts",
            ["account_id"],
            ["account_id"],
            ondelete="CASCADE",
        )


def _create_project_tables() -> None:
    now = datetime.now(timezone.utc)
    op.create_table(
        "projects",
        sa.Column("project_id", sa.String(36), primary_key=True),
        sa.Column("project_code", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("lifecycle_state", sa.String(32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_by_account_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"], ["accounts.account_id"], ondelete="RESTRICT",
            name="fk_projects_created_by_account_id_accounts",
        ),
        sa.UniqueConstraint("project_code", name="uq_projects_project_code"),
        sa.CheckConstraint(
            "lifecycle_state IN ('ACTIVE', 'SUSPENDED', 'ARCHIVED')", name="ck_projects_lifecycle_state"
        ),
    )
    op.create_index("ix_projects_lifecycle_state", "projects", ["lifecycle_state"])
    op.create_index("ix_projects_created_by_account_id", "projects", ["created_by_account_id"])

    bind = op.get_bind()
    creator = bind.execute(
        sa.text(
            "SELECT account_id FROM accounts WHERE platform_role = 'PLATFORM_ADMIN' AND enabled = :enabled "
            "ORDER BY username"
        ),
        {"enabled": True},
    ).scalar()
    account_count = int(bind.execute(sa.text("SELECT COUNT(*) FROM accounts")).scalar_one())
    if account_count and creator is None:
        raise RuntimeError(
            "cannot create the default project: legacy accounts exist but no enabled platform administrator owner was found"
        )
    projects = sa.table(
        "projects",
        sa.column("project_id", sa.String),
        sa.column("project_code", sa.String),
        sa.column("display_name", sa.String),
        sa.column("lifecycle_state", sa.String),
        sa.column("revision", sa.Integer),
        sa.column("created_by_account_id", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    bind.execute(projects.insert().values(
        project_id=DEFAULT_PROJECT_ID,
        project_code=DEFAULT_PROJECT_CODE,
        display_name="Default Project",
        lifecycle_state="ACTIVE",
        revision=1,
        created_by_account_id=creator,
        created_at=now,
        updated_at=now,
    ))

    op.create_table(
        "project_memberships",
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("project_role", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_account_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.account_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_account_id"], ["accounts.account_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("project_id", "account_id", name="pk_project_memberships"),
        sa.CheckConstraint(
            "project_role IN ('PROJECT_OWNER', 'PROJECT_USER')", name="ck_project_memberships_role"
        ),
    )
    op.create_index("ix_project_memberships_project_role", "project_memberships", ["project_role"])
    op.create_index("ix_project_memberships_enabled", "project_memberships", ["enabled"])
    op.create_index(
        "ix_project_memberships_account_enabled", "project_memberships", ["account_id", "enabled"]
    )
    bind.execute(
        sa.text(
            "INSERT INTO project_memberships "
            "(project_id, account_id, project_role, enabled, revision, created_by_account_id, created_at, updated_at) "
            "SELECT :project_id, account_id, "
            "CASE WHEN platform_role = 'PLATFORM_ADMIN' THEN 'PROJECT_OWNER' ELSE 'PROJECT_USER' END, "
            "accounts.enabled, 1, :creator, :created_at, :updated_at FROM accounts"
        ),
        {
            "project_id": DEFAULT_PROJECT_ID,
            "creator": creator,
            "created_at": now,
            "updated_at": now,
        },
    )


def _add_and_backfill_project_columns() -> dict[str, int]:
    bind = op.get_bind()
    counts = {
        table_name: int(bind.execute(sa.text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar_one())
        for table_name in PROJECT_OWNED_TABLES
    }
    for table_name in PROJECT_OWNED_TABLES:
        op.add_column(table_name, sa.Column("project_id", sa.String(36), nullable=True))
        bind.execute(
            sa.text(f'UPDATE "{table_name}" SET project_id = :project_id WHERE project_id IS NULL'),
            {"project_id": DEFAULT_PROJECT_ID},
        )
        _assert_no_nulls(table_name, "project_id")
        with op.batch_alter_table(table_name, recreate=_recreate_mode(), naming_convention=NAMING_CONVENTION) as batch:
            batch.alter_column("project_id", existing_type=sa.String(36), nullable=False)
    return counts


def _drop_legacy_foreign_keys() -> None:
    for table_name, columns, referred_table, _ in OLD_FOREIGN_KEYS:
        constraint_name = _fk_name(table_name, columns, referred_table)
        with op.batch_alter_table(table_name, recreate=_recreate_mode(), naming_convention=NAMING_CONVENTION) as batch:
            batch.drop_constraint(constraint_name, type_="foreignkey")


def _establish_project_constraints() -> None:
    feedback_action_unique = _unique_name("false_positive_feedback", ("action_id",))
    for table_name, old_columns in PROJECT_PRIMARY_KEYS.items():
        primary_key_name = _pk_name(table_name)
        with op.batch_alter_table(table_name, recreate=_recreate_mode(), naming_convention=NAMING_CONVENTION) as batch:
            if table_name == "model_parameter_profiles":
                batch.drop_constraint("uq_model_parameter_profile", type_="unique")
            if table_name == "false_positive_feedback":
                batch.drop_constraint(feedback_action_unique, type_="unique")
            batch.drop_constraint(primary_key_name, type_="primary")
            batch.create_primary_key(f"pk_{table_name}", ["project_id", *old_columns])
            for unique_name, columns in PROJECT_UNIQUES.get(table_name, ()):
                batch.create_unique_constraint(unique_name, list(columns))
            batch.create_foreign_key(
                f"fk_{table_name}_project_id_projects",
                "projects",
                ["project_id"],
                ["project_id"],
                ondelete="RESTRICT",
            )
            batch.create_index(f"ix_{table_name}_project_id", ["project_id"])

    with op.batch_alter_table(
        "alert_disposition_actions", recreate=_recreate_mode(), naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.drop_constraint("uq_alert_disposition_action", type_="unique")
        batch.create_unique_constraint(
            "uq_alert_disposition_action", ["project_id", "event_id", "status", "actor", "acted_at_us"]
        )
        batch.create_unique_constraint("uq_alert_disposition_actions_project_id", ["project_id", "id"])
        batch.create_foreign_key(
            "fk_alert_disposition_actions_project_id_projects",
            "projects",
            ["project_id"],
            ["project_id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_alert_disposition_actions_project_id", ["project_id"])
        batch.create_index("ix_alert_disposition_actions_project_event", ["project_id", "event_id"])

    for table_name in ("alert_rule_audits", "model_parameter_audits"):
        with op.batch_alter_table(table_name, recreate=_recreate_mode(), naming_convention=NAMING_CONVENTION) as batch:
            batch.create_foreign_key(
                f"fk_{table_name}_project_id_projects",
                "projects",
                ["project_id"],
                ["project_id"],
                ondelete="RESTRICT",
            )
            batch.create_index(f"ix_{table_name}_project_id", ["project_id"])

    for table_name, constraint_name, columns, referred_table, remote_columns, ondelete in PROJECT_FOREIGN_KEYS:
        with op.batch_alter_table(table_name, recreate=_recreate_mode(), naming_convention=NAMING_CONVENTION) as batch:
            batch.create_foreign_key(
                constraint_name,
                referred_table,
                list(columns),
                list(remote_columns),
                ondelete=ondelete,
            )

    extra_indexes = (
        ("alert_events", "ix_alert_events_project_updated", ("project_id", "updated_at")),
        ("alert_rules", "ix_alert_rules_project_enabled", ("project_id", "enabled")),
        ("alert_rule_bindings", "ix_alert_rule_bindings_project_source", ("project_id", "source_id")),
        ("alert_rule_audits", "ix_alert_rule_audits_project_rule", ("project_id", "rule_id")),
        ("model_parameter_profiles", "ix_model_parameter_profiles_project_model", ("project_id", "model_id")),
        ("model_parameter_audits", "ix_model_parameter_audits_project_profile", ("project_id", "profile_key")),
        ("alert_delivery_receipts", "ix_alert_delivery_receipts_project_created", ("project_id", "created_at")),
        ("stream_configs", "ix_stream_configs_project_enabled", ("project_id", "enabled")),
    )
    for table_name, index_name, columns in extra_indexes:
        op.create_index(index_name, table_name, list(columns))


def _create_assignment_and_audit_tables() -> None:
    json_document = _json_document()
    op.create_table(
        "project_model_assignments",
        sa.Column("assignment_id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("scenario", sa.String(128), nullable=False),
        sa.Column("model_id", sa.String(255), nullable=False),
        sa.Column("model_version", sa.String(128), nullable=False),
        sa.Column("parameter_profile_key", sa.String(512), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_account_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_account_id"], ["accounts.account_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["project_id", "parameter_profile_key"],
            ["model_parameter_profiles.project_id", "model_parameter_profiles.profile_key"],
            ondelete="RESTRICT",
            name="fk_project_model_assignments_project_profile",
        ),
        sa.UniqueConstraint(
            "project_id", "scenario", name="uq_project_model_assignments_project_scenario"
        ),
    )
    op.create_index("ix_project_model_assignments_project_id", "project_model_assignments", ["project_id"])
    op.create_index("ix_project_model_assignments_model_id", "project_model_assignments", ["model_id"])
    op.create_index("ix_project_model_assignments_enabled", "project_model_assignments", ["enabled"])
    op.create_index(
        "ix_project_model_assignments_project_enabled",
        "project_model_assignments",
        ["project_id", "enabled"],
    )

    op.create_table(
        "project_audit_events",
        sa.Column("audit_id", sa.String(36), primary_key=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("actor_account_id", sa.String(36), nullable=True),
        sa.Column("actor_service_principal_id", sa.String(36), nullable=True),
        sa.Column("platform_role", sa.String(32), nullable=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("project_role", sa.String(32), nullable=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("target_type", sa.String(128), nullable=False),
        sa.Column("target_id", sa.String(512), nullable=True),
        sa.Column("previous_revision", sa.Integer(), nullable=True),
        sa.Column("new_revision", sa.Integer(), nullable=True),
        sa.Column("change_summary", json_document, nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("failure_code", sa.String(128), nullable=True),
        sa.ForeignKeyConstraint(["actor_account_id"], ["accounts.account_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="RESTRICT"),
        sa.CheckConstraint("outcome IN ('SUCCESS', 'DENIED', 'FAILED')", name="ck_project_audit_events_outcome"),
    )
    for index_name, columns in (
        ("ix_project_audit_events_occurred_at", ("occurred_at",)),
        ("ix_project_audit_events_request_id", ("request_id",)),
        ("ix_project_audit_events_actor_account_id", ("actor_account_id",)),
        ("ix_project_audit_events_project_id", ("project_id",)),
        ("ix_project_audit_events_action", ("action",)),
        ("ix_project_audit_events_project_time", ("project_id", "occurred_at")),
        ("ix_project_audit_events_target", ("project_id", "target_type", "target_id")),
    ):
        op.create_index(index_name, "project_audit_events", list(columns))


def upgrade() -> None:
    _validate_legacy_owner()
    _add_identity_columns()
    _create_project_tables()
    original_counts = _add_and_backfill_project_columns()
    _drop_legacy_foreign_keys()
    _establish_project_constraints()
    _create_assignment_and_audit_tables()

    bind = op.get_bind()
    for table_name, expected_count in original_counts.items():
        actual_count = int(bind.execute(sa.text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar_one())
        if actual_count != expected_count:
            raise RuntimeError(
                f"multi-project migration row-count mismatch for {table_name}: "
                f"expected {expected_count}, found {actual_count}"
            )


def _reject_lossy_downgrade() -> None:
    bind = op.get_bind()
    non_default_projects = int(bind.execute(sa.text(
        "SELECT COUNT(*) FROM projects WHERE project_id <> :project_id"
    ), {"project_id": DEFAULT_PROJECT_ID}).scalar_one())
    assignments = int(bind.execute(sa.text("SELECT COUNT(*) FROM project_model_assignments")).scalar_one())
    audits = int(bind.execute(sa.text("SELECT COUNT(*) FROM project_audit_events")).scalar_one())
    non_default_rows = 0
    for table_name in PROJECT_OWNED_TABLES:
        non_default_rows += int(bind.execute(sa.text(
            f'SELECT COUNT(*) FROM "{table_name}" WHERE project_id <> :project_id'
        ), {"project_id": DEFAULT_PROJECT_ID}).scalar_one())
    if non_default_projects or assignments or audits or non_default_rows:
        raise RuntimeError(
            "multi-project downgrade refused because it would discard project data, assignments, or audit history"
        )


def downgrade() -> None:
    _reject_lossy_downgrade()
    op.drop_table("project_audit_events")
    op.drop_table("project_model_assignments")

    for table_name, constraint_name, _, _, _, _ in reversed(PROJECT_FOREIGN_KEYS):
        with op.batch_alter_table(table_name, recreate=_recreate_mode(), naming_convention=NAMING_CONVENTION) as batch:
            batch.drop_constraint(constraint_name, type_="foreignkey")

    extra_indexes = (
        ("alert_events", "ix_alert_events_project_updated"),
        ("alert_rules", "ix_alert_rules_project_enabled"),
        ("alert_rule_bindings", "ix_alert_rule_bindings_project_source"),
        ("alert_rule_audits", "ix_alert_rule_audits_project_rule"),
        ("model_parameter_profiles", "ix_model_parameter_profiles_project_model"),
        ("model_parameter_audits", "ix_model_parameter_audits_project_profile"),
        ("alert_delivery_receipts", "ix_alert_delivery_receipts_project_created"),
        ("stream_configs", "ix_stream_configs_project_enabled"),
    )
    for table_name, index_name in extra_indexes:
        op.drop_index(index_name, table_name=table_name)

    for table_name, old_columns in reversed(tuple(PROJECT_PRIMARY_KEYS.items())):
        with op.batch_alter_table(table_name, recreate=_recreate_mode(), naming_convention=NAMING_CONVENTION) as batch:
            batch.drop_constraint(f"fk_{table_name}_project_id_projects", type_="foreignkey")
            batch.drop_index(f"ix_{table_name}_project_id")
            for unique_name, _ in PROJECT_UNIQUES.get(table_name, ()):
                batch.drop_constraint(unique_name, type_="unique")
            batch.drop_constraint(_pk_name(table_name), type_="primary")
            batch.create_primary_key(f"pk_{table_name}", list(old_columns))
            if table_name == "model_parameter_profiles":
                batch.create_unique_constraint(
                    "uq_model_parameter_profile", ["model_id", "model_version", "platform"]
                )

    with op.batch_alter_table(
        "alert_disposition_actions", recreate=_recreate_mode(), naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.drop_constraint("fk_alert_disposition_actions_project_id_projects", type_="foreignkey")
        batch.drop_index("ix_alert_disposition_actions_project_id")
        batch.drop_index("ix_alert_disposition_actions_project_event")
        batch.drop_constraint("uq_alert_disposition_actions_project_id", type_="unique")
        batch.drop_constraint("uq_alert_disposition_action", type_="unique")
        batch.create_unique_constraint(
            "uq_alert_disposition_action", ["event_id", "status", "actor", "acted_at_us"]
        )

    for table_name in ("alert_rule_audits", "model_parameter_audits"):
        with op.batch_alter_table(table_name, recreate=_recreate_mode(), naming_convention=NAMING_CONVENTION) as batch:
            batch.drop_constraint(f"fk_{table_name}_project_id_projects", type_="foreignkey")
            batch.drop_index(f"ix_{table_name}_project_id")

    for table_name, columns, referred_table, ondelete in OLD_FOREIGN_KEYS:
        with op.batch_alter_table(table_name, recreate=_recreate_mode(), naming_convention=NAMING_CONVENTION) as batch:
            batch.create_foreign_key(
                f"fk_{table_name}_{columns[0]}_{referred_table}",
                referred_table,
                list(columns),
                list(columns if table_name != "false_positive_feedback" or columns != ("action_id",) else ("id",)),
                ondelete=ondelete,
            )

    with op.batch_alter_table(
        "false_positive_feedback", recreate=_recreate_mode(), naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.create_unique_constraint("uq_false_positive_feedback_action_id", ["action_id"])

    for table_name in reversed(PROJECT_OWNED_TABLES):
        with op.batch_alter_table(table_name, recreate=_recreate_mode(), naming_convention=NAMING_CONVENTION) as batch:
            batch.drop_column("project_id")

    op.drop_table("project_memberships")
    op.drop_table("projects")

    with op.batch_alter_table("account_sessions", recreate=_recreate_mode(), naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint("fk_account_sessions_account_id_accounts", type_="foreignkey")

    with op.batch_alter_table("accounts", recreate=_recreate_mode(), naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint("uq_accounts_username", type_="unique")
        batch.drop_constraint(_pk_name("accounts"), type_="primary")
        batch.create_primary_key("pk_accounts", ["username"])

    with op.batch_alter_table("account_sessions", recreate=_recreate_mode(), naming_convention=NAMING_CONVENTION) as batch:
        batch.create_foreign_key(
            "fk_account_sessions_username_accounts",
            "accounts",
            ["username"],
            ["username"],
            ondelete="CASCADE",
        )
        batch.drop_index("ix_account_sessions_account_id")
        batch.drop_column("account_id")
    with op.batch_alter_table("accounts", recreate=_recreate_mode(), naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_index("ix_accounts_platform_role")
        batch.drop_constraint("ck_accounts_platform_role", type_="check")
        batch.drop_column("platform_role")
        batch.drop_column("account_id")
