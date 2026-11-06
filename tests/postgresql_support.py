from __future__ import annotations

from contextlib import contextmanager
import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import settings


@contextmanager
def isolated_postgresql_url(prefix: str, *, revision: str = "head"):
    """Create a migrated random schema without exposing tests to public."""
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for PostgreSQL integration tests")
    base_url = make_url(settings.database_url)
    if base_url.get_backend_name() != "postgresql":
        raise RuntimeError("PostgreSQL integration tests require a PostgreSQL DATABASE_URL")

    schema_name = f"{prefix}_{uuid.uuid4().hex}"
    admin_url = base_url.update_query_dict({"options": "-csearch_path=pg_catalog"})
    isolated_url = base_url.update_query_dict({"options": f"-csearch_path={schema_name}"})
    admin_engine = create_engine(admin_url, pool_pre_ping=True)
    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url",
        isolated_url.render_as_string(hide_password=False).replace("%", "%%"),
    )
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
        command.upgrade(config, revision)
        yield isolated_url.render_as_string(hide_password=False)
    finally:
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        admin_engine.dispose()
