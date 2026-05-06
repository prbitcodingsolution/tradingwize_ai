"""Alembic migration environment.

Builds the SQLAlchemy URL from the same env vars that
`database_utility/database.py` reads (DB_HOST / DB_PORT / DB_NAME /
DB_USER / DB_PASSWORD), so `alembic upgrade head` always targets the
same database the app does.

There is no ORM metadata here — migrations are hand-written SQL so we
don't pay the cost of maintaining duplicate model definitions just for
Alembic's autogenerate mode.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

# Load .env so DB_* env vars are available when the command runs from
# the project root (same contract the rest of the codebase uses).
load_dotenv()

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _build_db_url() -> str:
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD", "")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "stock_analysis")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"


_db_url = _build_db_url()
config.set_main_option("sqlalchemy.url", _db_url)

# Hand-written migrations → no ORM metadata.
target_metadata = None


def run_migrations_offline() -> None:
    """Emit SQL scripts without connecting to a DB."""
    context.configure(
        url=_db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the live database."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
