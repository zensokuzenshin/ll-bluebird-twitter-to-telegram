"""
Database module for the Twitter to Telegram forwarder.
Handles PostgreSQL connections and operations.
"""

import glob
import logging
import os
import re
from typing import Any, Dict, Optional, Tuple

import asyncpg

import config

# Configure module-specific logger
logger = logging.getLogger(__name__)

# Global connection pool
_pool: Optional[asyncpg.Pool] = None


async def _setup_connection(conn: asyncpg.Connection) -> None:
    await conn.execute("SET application_name = 'lovelive-bluebird-twitter-to-telegram'")
    # Set a statement timeout to prevent long-running queries
    await conn.execute("SET statement_timeout = '30s'")


async def _create_connection_pool() -> asyncpg.Pool:
    """
    Create a connection pool to the PostgreSQL/CockroachDB database.
    This is the actual implementation that will be retried.

    Returns:
        asyncpg.Pool: The connection pool
    """
    logger.info(f"Creating database connection pool to {config.common.POSTGRES_HOST}")

    # Create the connection pool with a setup callback for each new connection
    return await asyncpg.create_pool(
        dsn=config.common.POSTGRES_DSN,
        min_size=2,
        max_size=10,
        # This function is called for each new connection
        setup=_setup_connection,
        # Connection timeout (5 seconds)
        timeout=5.0,
        # CockroachDB can sometimes be slower to respond
        command_timeout=10.0,
    )


async def get_connection_pool() -> asyncpg.Pool:
    """
    Get or create a connection pool to the PostgreSQL database.
    Uses retry with exponential backoff for connection attempts.

    Returns:
        asyncpg.Pool: The connection pool
    """
    global _pool

    if _pool is None:
        try:
            # Import retry utility here to avoid circular imports
            from .retry import retry_with_backoff

            # Retry connection pool creation with backoff
            _pool = await retry_with_backoff(
                _create_connection_pool,
                max_retries=5,  # More retries for initial connection
                initial_backoff=0.5,  # Start with 500ms
                max_backoff=5.0,  # Maximum 5 seconds between retries
            )

        except Exception as e:
            logger.error(
                f"Failed to create database connection pool after retries: {str(e)}"
            )
            raise

    return _pool


async def close_connection_pool():
    """Close the database connection pool."""
    global _pool

    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database connection pool closed")


async def _check_table_exists(conn: asyncpg.Connection, table_name: str) -> bool:
    """
    Helper function to check if a table exists.
    This function is used by get_current_schema_version and is designed to be retried.
    Uses an explicit transaction to avoid "not in a transaction" errors.

    Args:
        conn: The database connection to use
        table_name: The name of the table to check

    Returns:
        bool: True if the table exists, False otherwise
    """
    # Start an explicit transaction to avoid "not in a transaction" errors
    async with conn.transaction():
        return await conn.fetchval(f"""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = '{table_name}'
            )
        """)


def get_expected_schema_version() -> str:
    """
    Dynamically determine the expected database schema version from the most recent Alembic migration.

    This function finds all migration files in the alembic/versions directory, parses their
    filenames (which should follow the pattern 'seq_date_comment.py' where seq is a number),
    and returns the revision ID from the file with the highest sequence number.

    Returns:
        str: The expected schema version (revision ID of the most recent migration)
    """
    # Get the project root directory
    project_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )

    # Path to Alembic versions directory
    versions_dir = os.path.join(project_root, "alembic", "versions")

    # Find all migration files
    migration_files = glob.glob(os.path.join(versions_dir, "*.py"))

    if not migration_files:
        logger.error(f"No migration files found in {versions_dir}")
        return ""

    # Regular expression to extract sequence numbers from filenames
    # Expects filenames like: 001_20250608_initial_schema.py
    filename_pattern = re.compile(r"^(\d+)_.*\.py$")

    # Regular expression to extract revision IDs from migration files
    # This pattern matches both "revision = '123abc'" and "revision: str = '123abc'" formats
    revision_pattern = re.compile(
        r"revision(?:\s*:\s*\w+)?\s*=\s*['\"]([0-9a-f]+)['\"]"
    )

    # Dictionary to store sequence numbers, file paths, and revision IDs
    migrations = {}

    # Parse each migration file to extract sequence number and revision ID
    for file_path in migration_files:
        filename = os.path.basename(file_path)
        filename_match = filename_pattern.match(filename)

        if not filename_match:
            logger.warning(
                f"Migration file {filename} does not follow the expected naming pattern"
            )
            continue

        try:
            # Extract sequence number from filename
            seq_num = int(filename_match.group(1))

            # Extract revision ID from file content
            with open(file_path, "r") as f:
                content = f.read()

                # Try to match revision ID in different formats
                revision_match = revision_pattern.search(content)

                # If not found, also try to find it in a comment line like "Revision ID: 123abc"
                if not revision_match:
                    revision_id_comment = re.search(
                        r"Revision ID:\s*([0-9a-f]+)", content
                    )
                    if revision_id_comment:
                        revision_id = revision_id_comment.group(1)
                        logger.info(f"Found revision ID in comment: {revision_id}")
                    else:
                        logger.warning(f"Could not find revision ID in {filename}")
                        continue
                else:
                    revision_id = revision_match.group(1)
                migrations[seq_num] = {
                    "file_path": file_path,
                    "revision_id": revision_id,
                    "filename": filename,
                }
        except Exception as e:
            logger.warning(f"Failed to parse migration file {filename}: {str(e)}")

    if not migrations:
        logger.error(
            "Could not find any valid migration files with the expected naming pattern"
        )
        return ""

    # Get the migration with the highest sequence number
    latest_seq_num = max(migrations.keys())
    latest_migration = migrations[latest_seq_num]
    latest_revision = latest_migration["revision_id"]

    logger.info(
        f"Latest migration (seq: {latest_seq_num}) is {latest_revision} from {latest_migration['filename']}"
    )

    return latest_revision


async def get_current_schema_version() -> Optional[str]:
    """
    Get the current database schema version from the alembic_version table.
    This function is used by check_schema_version and is designed to be retried.
    Uses an explicit transaction to avoid "not in a transaction" errors.

    Returns:
        Optional[str]: The current schema version, or None if not found
    """
    pool = await get_connection_pool()

    async with pool.acquire() as conn:
        # First check if the alembic_version table exists
        table_exists = await _check_table_exists(conn, "alembic_version")

        if not table_exists:
            logger.warning(
                "alembic_version table does not exist - database has not been initialized"
            )
            return None

        # Start an explicit transaction to avoid "not in a transaction" errors
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
    parent_tweet_id: Optional[str] = None,
    llm_provider: Optional[str] = None,
) -> Any:
    """
    Helper function to insert a translated message record.
    This function is used by store_translated_message and is designed to be retried.
    Supports both integer and UUID primary keys.

    Args:
        conn: The database connection to use
        telegram_message_id: The Telegram message ID
        tweet_id: The Tweet ID
        tweet_url: The Tweet URL
        character_name: The character name used for the message
        translation_text: The translated text
        original_text: The original text
        parent_tweet_id: The parent tweet ID if this is a reply
        llm_provider: The LLM provider used for translation

    Returns:
        Any: The ID of the inserted record (can be int or UUID)
    """
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
    parent_tweet_id: Optional[str] = None,
    llm_provider: Optional[str] = None,
) -> Any:
    """
    Store a translated message in the database with retry capability.
    Supports both integer and UUID primary keys.

    Args:
        telegram_message_id: The Telegram message ID
        tweet_id: The Tweet ID
        tweet_url: The Tweet URL
        character_name: The character name used for the message
        translation_text: The translated text
        original_text: The original text
        parent_tweet_id: The parent tweet ID if this is a reply
        llm_provider: The LLM provider used for translation

    Returns:
        Any: The ID of the inserted record (can be int or UUID)
    """
    from .retry import retry_db_operation

    pool = await get_connection_pool()

    async with pool.acquire() as conn:
        # Wrap the database operation with retry logic
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
            f"Stored translated message: telegram_id={telegram_message_id}, tweet_id={tweet_id}"
        )
        return record_id


async def _fetch_telegram_message_id(
    conn: asyncpg.Connection, tweet_id: str
) -> Optional[Dict[str, Any]]:
    """
    Helper function to fetch the Telegram message ID for a tweet.
    This function is used by get_telegram_message_id_for_tweet and is designed to be retried.

    Args:
        conn: The database connection to use
        tweet_id: The Tweet ID

    Returns:
        Optional[Dict[str, Any]]: The row containing the Telegram message ID, or None if not found
    """
    return await conn.fetchrow(
        """
        SELECT telegram_message_id 
        FROM translated_messages 
        WHERE tweet_id = $1
        """,
        tweet_id,
    )


async def get_telegram_message_id_for_tweet(tweet_id: str) -> Optional[int]:
    """
    Get the Telegram message ID for a given tweet ID with retry capability.

    Args:
        tweet_id: The Tweet ID

    Returns:
        Optional[int]: The Telegram message ID, or None if not found
    """
    from .retry import retry_db_operation

    pool = await get_connection_pool()

    async with pool.acquire() as conn:
        # Wrap the database operation with retry logic
        row = await retry_db_operation(
            _fetch_telegram_message_id,
            conn,
            tweet_id,
        )

        if row:
            return row["telegram_message_id"]
        return None


async def check_db_connection() -> Tuple[bool, Optional[str]]:
    """
    Check database connectivity by attempting a simple query.
    Uses direct transaction handling to avoid issues.

    Returns:
        Tuple[bool, Optional[str]]: A tuple containing:
            - A boolean indicating if the connection is healthy
            - An optional error message if the connection is not healthy
    """
    try:
        # Get connection pool (or create if not exists)
        pool = await get_connection_pool()

        # Perform a simple query with explicit transaction
        async with pool.acquire() as conn:
            # Use a simple query that works on both PostgreSQL and CockroachDB
            query = "SELECT 1 as connected"

            # Use explicit transaction
            async with conn.transaction():
                result = await conn.fetchval(query)

            if result == 1:
                logger.debug("Database health check passed")
                return True, None
            else:
                logger.warning(
                    f"Database health check failed: unexpected result {result}"
                )
                return False, f"Unexpected result: {result}"

    except Exception as e:
        logger.error(f"Database health check failed: {str(e)}")
        return False, str(e)


async def get_last_message_tweet_id() -> Optional[str]:
    """
    Get the tweet ID of the most recently stored translated message.

    Returns:
        Optional[str]: The tweet ID of the last translated message, or None if no messages exist
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

            if row:
                return row["tweet_id"]
            return None

    except Exception as e:
        logger.error(f"Failed to fetch last message tweet ID: {str(e)}")
        return None
