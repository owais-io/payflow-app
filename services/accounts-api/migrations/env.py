"""Alembic environment for accounts-api.

Connects with DATABASE_URL only (nothing in alembic.ini, none of the app's
other settings), and compares against the app's own models.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app import models  # noqa: F401  (importing registers the tables on Base.metadata)
from app.db import Base

# Each service keeps its own migration history in its own version table,
# so accounts-api and payments-api can share one database without clashing.
VERSION_TABLE = "alembic_version_accounts"

# Tables this service owns. Alembic ignores every other table in the shared database:
# payments-api's transactions table and other services' version tables.
# So autogenerate never creates or drops them, and `alembic check` doesn't report them.
OWNED_TABLES = {"accounts"}

# The Alembic Config object: access to the values in alembic.ini.
config = context.config

# Set up Python logging from the [loggers] sections of alembic.ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The schema migrations are generated from (autogenerate) and checked against (alembic check).
target_metadata = Base.metadata


def database_url() -> str:
    """Only DATABASE_URL: migrations don't need the rest of the app's config."""
    try:
        return os.environ["DATABASE_URL"]
    except KeyError:
        raise SystemExit("DATABASE_URL is not set") from None


def include_object(obj, name, type_, reflected, compare_to):
    """Decide which database objects Alembic looks at.

    Tables: only the ones this service owns. Columns, indexes and constraints
    are kept; they only reach this point for tables that passed the check.
    """
    if type_ == "table":
        return name in OWNED_TABLES
    return True


def run_migrations_offline() -> None:
    """Offline mode (`alembic upgrade head --sql`): print the SQL instead of running it.

    Only needs a URL, not a live connection.
    """
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Online mode (normal): open one connection, apply the migrations, close it.

    NullPool: a short-lived migration process needs no connection pool.
    """
    connectable = create_engine(database_url(), poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=VERSION_TABLE,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
