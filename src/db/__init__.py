"""
Database module for the Twitter to Telegram forwarder.
Handles PostgreSQL connections and operations.
"""

import logging
import re
from pathlib import Path
from typing import Any

import asyncpg

import config

from .retry import retry_db_operation, retry_with_backoff

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
# Migrations are named like "001_20250608_initial_schema.py"; the leading
# sequence number is what orders them.
_MIGRATION_FILENAME = re.compile(r"^(\d+)_.*\.py$")
_REVISION = re.compile(
    r"^revision(?:\s*:\s*\w+)?\s*=\s*['\"]([0-9a-f]+)['\"]", re.MULTILINE
)


async def _setup_connection(conn: asyncpg.Connection) -> None:
    await conn.execute("SET application_name = 'lovelive-bluebird-twitter-to-telegram'")
    await conn.execute("SET statement_timeout = '30s'")


async def _create_connection_pool() -> asyncpg.Pool:
    logger.info("Creating database connection pool to %s", config.common.POSTGRES_HOST)

    return await asyncpg.create_pool(
        dsn=config.common.POSTGRES_DSN,
        min_size=2,
        max_size=10,
        setup=_setup_connection,
        timeout=5.0,
        # CockroachDB can be slow to respond
        command_timeout=10.0,
    )


async def get_connection_pool() -> asyncpg.Pool:
    """Get or create the pool, retrying with backoff while the DB comes up."""
    global _pool

    if _pool is None:
        try:
            _pool = await retry_with_backoff(
                _create_connection_pool,
                max_retries=5,
                initial_backoff=0.5,
                max_backoff=5.0,
            )
        except Exception as e:
            logger.error(
                "Failed to create database connection pool after retries: %s", e
            )
            raise

    return _pool


async def close_connection_pool() -> None:
    """Close the database connection pool."""
    global _pool

    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database connection pool closed")


async def _check_table_exists(conn: asyncpg.Connection, table_name: str) -> bool:
    # Explicit transaction; CockroachDB otherwise errors with "not in a transaction"
    async with conn.transaction():
        return await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = $1
            )
            """,
            table_name,
        )


def get_expected_schema_version() -> str:
    """Revision ID of the highest-numbered migration, or "" if none is readable."""
    revisions: dict[int, str] = {}

    for path in _VERSIONS_DIR.glob("*.py"):
        filename_match = _MIGRATION_FILENAME.match(path.name)
        if not filename_match:
            logger.warning(
                "Migration file %s does not follow the expected naming pattern",
                path.name,
            )
            continue

        revision_match = _REVISION.search(path.read_text())
        if not revision_match:
            logger.warning("Could not find revision ID in %s", path.name)
            continue

        revisions[int(filename_match.group(1))] = revision_match.group(1)

    if not revisions:
        logger.error("No readable migration files found in %s", _VERSIONS_DIR)
        return ""

    latest_seq = max(revisions)
    logger.info("Latest migration (seq: %d) is %s", latest_seq, revisions[latest_seq])
    return revisions[latest_seq]


async def get_current_schema_version() -> str | None:
    pool = await get_connection_pool()

    async with pool.acquire() as conn:
        if not await _check_table_exists(conn, "alembic_version"):
            logger.warning(
                "alembic_version table does not exist - database has not been initialized"
            )
            return None

        async with conn.transaction():
            return await conn.fetchval("SELECT version_num FROM alembic_version")


async def _insert_translated_message(
    conn: asyncpg.Connection,
    telegram_message_id: int,
    tweet_id: str,
    tweet_url: str,
    character_name: str,
    translation_text: str,
    original_text: str,
    parent_tweet_id: str | None = None,
    llm_provider: str | None = None,
) -> Any:
    row = await conn.fetchrow(
        """
    INSERT INTO translated_messages
    (telegram_message_id, tweet_id, tweet_url, parent_tweet_id, character_name,
     llm_provider, translation_text, original_text)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
    RETURNING id
    """,
        telegram_message_id,
        tweet_id,
        tweet_url,
        parent_tweet_id,
        character_name,
        llm_provider,
        translation_text,
        original_text,
    )

    return row["id"]


async def store_translated_message(
    telegram_message_id: int,
    tweet_id: str,
    tweet_url: str,
    character_name: str,
    translation_text: str,
    original_text: str,
    parent_tweet_id: str | None = None,
    llm_provider: str | None = None,
) -> Any:
    pool = await get_connection_pool()

    async with pool.acquire() as conn:
        record_id = await retry_db_operation(
            _insert_translated_message,
            conn,
            telegram_message_id,
            tweet_id,
            tweet_url,
            character_name,
            translation_text,
            original_text,
            parent_tweet_id,
            llm_provider,
        )

        logger.info(
            "Stored translated message: telegram_id=%s, tweet_id=%s",
            telegram_message_id,
            tweet_id,
        )
        return record_id


async def _fetch_telegram_message_id(
    conn: asyncpg.Connection, tweet_id: str
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT telegram_message_id
        FROM translated_messages
        WHERE tweet_id = $1
        """,
        tweet_id,
    )


async def get_telegram_message_id_for_tweet(tweet_id: str) -> int | None:
    """Get the Telegram message ID a given tweet was forwarded as, if any."""
    pool = await get_connection_pool()

    async with pool.acquire() as conn:
        row = await retry_db_operation(_fetch_telegram_message_id, conn, tweet_id)
        return row["telegram_message_id"] if row else None


async def check_db_connection() -> tuple[bool, str | None]:
    """Whether the database is reachable, plus the error if it is not."""
    try:
        pool = await get_connection_pool()

        async with pool.acquire() as conn, conn.transaction():
            result = await conn.fetchval("SELECT 1 as connected")

        if result == 1:
            logger.debug("Database health check passed")
            return True, None

        logger.warning("Database health check failed: unexpected result %r", result)
        return False, f"Unexpected result: {result}"

    except Exception as e:
        logger.error("Database health check failed: %s", e)
        return False, str(e)


async def get_last_message_tweet_id() -> str | None:
    """Tweet ID of the most recently stored message.

    Snowflakes are stored as text but are all the same length today, so
    ordering lexicographically also orders them by post time.
    """
    try:
        pool = await get_connection_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT tweet_id
                FROM translated_messages
                ORDER BY tweet_id DESC
                LIMIT 1
                """
            )

            return row["tweet_id"] if row else None

    except Exception as e:
        logger.error("Failed to fetch last message tweet ID: %s", e)
        return None
