from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.database import Base
from app.model_updates import models as _model_update_models
from app.app_updates import models as _app_update_models


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

database_url = config.get_main_option("sqlalchemy.url", "").strip()
if not database_url:
    from app.config import settings

    database_url = settings.database_url or ""
if not database_url:
    raise RuntimeError("DATABASE_URL is required to run database migrations")

config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    def configure_connection(connection):
        def include_object(obj, name, type_, reflected, compare_to):
            conditional = getattr(obj, '_ddl_if', None)
            if type_ == 'index' and conditional and conditional.dialect:
                dialects = (conditional.dialect,) if isinstance(conditional.dialect, str) else conditional.dialect
                return connection.dialect.name in dialects
            return True
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True,
                          include_object=include_object)

    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        configure_connection(supplied_connection)
        with context.begin_transaction():
            context.run_migrations()
        return
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # Conditional SQLite indexes must be excluded on PG for both CLI paths.
        configure_connection(connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
