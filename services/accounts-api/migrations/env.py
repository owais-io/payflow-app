"""Alembic environment for accounts-api.

The database URL comes from DATABASE_URL via the app's own Settings
(nothing in alembic.ini), and the target schema is the app's own models.
"""

from logging.config import fileConfig

from alembic import context

from app import models  # noqa: F401  (importing registers the tables on Base.metadata)
from app.config import get_settings
from app.db import Base, get_engine

# Each service keeps its own migration history in its own version table,
# so accounts-api and payments-api can share one database without clashing.
VERSION_TABLE = "alembic_version_accounts"

# The Alembic Config object: access to the values in alembic.ini.
config = context.config

# Set up Python logging from the [loggers] sections of alembic.ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The schema migrations are generated from (autogenerate) and checked against (alembic check).
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Offline mode (`alembic upgrade head --sql`): print the SQL instead of running it.

    Only needs a URL, not a live connection.
    """
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Online mode (normal): connect with the app's engine and apply the migrations."""
    connectable = get_engine()

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=VERSION_TABLE,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
