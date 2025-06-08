from logging.config import fileConfig
import os
import sys
import logging

from sqlalchemy import engine_from_config
from sqlalchemy import pool, text
from sqlalchemy.engine import Engine
from sqlalchemy.dialects import postgresql

from alembic import context

# Add the src directory to the Python path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

# Import config for DSN
from config.common import POSTGRES_DSN
# SQLAlchemy requires distinct DSN for CRDB
dsn = POSTGRES_DSN.replace("postgresql://", "cockroachdb://")

# Set up logger
logger = logging.getLogger("alembic.env")

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Override the SQLAlchemy URL with our DSN from environment
config.set_main_option("sqlalchemy.url", dsn)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No metadata since we're not using SQLAlchemy ORM
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = dsn
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    
    Includes special handling for CockroachDB.
    """
    # Use the DSN from config instead of relying on sqlalchemy.url in the config file
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = dsn
    
    # Add CockroachDB-specific settings
    # These help with transaction retry logic and performance
    cockroach_opts = {
        "connect_args": {
            "application_name": "lovelive-bluebird-twitter-to-telegram-migration",
        }
    }
    configuration.update(cockroach_opts)
    
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Configure Alembic context
        context.configure(
            connection=connection, 
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
