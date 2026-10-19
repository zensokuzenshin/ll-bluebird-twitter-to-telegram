"""
Utility functions for retrying database operations with exponential backoff.
"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

import asyncpg

# Configure module-specific logger
logger = logging.getLogger(__name__)

# Default retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_INITIAL_BACKOFF = 0.1  # 100ms
DEFAULT_MAX_BACKOFF = 1.0  # 1 second
DEFAULT_BACKOFF_FACTOR = 2.0
DEFAULT_JITTER = 0.1  # 10% jitter

# Default retryable exceptions
DEFAULT_RETRYABLE_EXCEPTIONS = (
    # Connection-related errors
    asyncpg.exceptions.ConnectionDoesNotExistError,
    asyncpg.exceptions.InterfaceError,
    asyncpg.exceptions.TooManyConnectionsError,
    asyncpg.exceptions.PostgresConnectionError,
    asyncpg.exceptions.ConnectionFailureError,
    # Transaction-related errors
    asyncpg.exceptions.DeadlockDetectedError,
    asyncpg.exceptions.SerializationError,
    # Query-related errors
    asyncpg.exceptions.QueryCanceledError,  # For statement timeout
)


def is_retryable_error(e: Exception) -> bool:
    """
    Determine if an exception is retryable.

    Args:
        e: The exception to check

    Returns:
        bool: True if the exception is retryable, False otherwise
    """
    return isinstance(e, DEFAULT_RETRYABLE_EXCEPTIONS)


async def retry_with_backoff[T](
    operation: Callable[..., Awaitable[T]],
    *args: Any,
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_backoff: float = DEFAULT_INITIAL_BACKOFF,
    max_backoff: float = DEFAULT_MAX_BACKOFF,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    jitter: float = DEFAULT_JITTER,
    **kwargs: Any,
) -> T:
    """
    Retry an async operation with exponential backoff.

    Args:
        operation: The async function to retry
        *args: Positional arguments to pass to the operation
        max_retries: Maximum number of retries
        initial_backoff: Initial backoff time in seconds
        max_backoff: Maximum backoff time in seconds
        backoff_factor: Multiplicative factor for backoff after each retry
        jitter: Random jitter factor to add to backoff (0.0-1.0)
        **kwargs: Keyword arguments to pass to the operation

    Returns:
        The result of the operation

    Raises:
        The last encountered exception if all retries fail
    """
    retries = 0
    last_exception = None

    # Try the operation until it succeeds or we reach max_retries
    while retries <= max_retries:
        try:
            if retries > 0:
                logger.debug(
                    "Retry attempt %d/%d for operation %s",
                    retries,
                    max_retries,
                    operation.__name__,
                )
            return await operation(*args, **kwargs)

        except Exception as e:
            last_exception = e

            # Check if this exception is retryable
            if not is_retryable_error(e):
                # Not a retryable exception, reraise immediately
                logger.warning(
                    "Non-retryable exception in %s: %s", operation.__name__, e
                )
                raise

            # Check if we've reached max retries
            if retries >= max_retries:
                logger.error(
                    "Max retries (%d) reached for %s: %s",
                    max_retries,
                    operation.__name__,
                    e,
                )
                raise

            backoff_time = min(initial_backoff * (backoff_factor**retries), max_backoff)

            # Add jitter (random variation) to avoid thundering herd problem
            jitter_amount = backoff_time * jitter * random.uniform(-1, 1)
            final_backoff = max(
                0.001, backoff_time + jitter_amount
            )  # Ensure positive backoff

            logger.warning(
                "Retryable error in %s: %s. Retrying in %.3fs (attempt %d/%d)",
                operation.__name__,
                e,
                final_backoff,
                retries + 1,
                max_retries,
            )

            # Wait before retrying
            await asyncio.sleep(final_backoff)

            retries += 1

    # We should never reach here due to the raise in the loop, but just in case
    if last_exception:
        raise last_exception

    # This should never happen, but needed for type checking
    raise RuntimeError("Unexpected error in retry logic")


async def retry_db_operation[T](
    operation: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any
) -> T:
    """
    Retry a database operation with the default retry configuration.

    Args:
        operation: The async database operation to retry
        *args: Positional arguments to pass to the operation
        **kwargs: Keyword arguments to pass to the operation

    Returns:
        The result of the operation
    """
    return await retry_with_backoff(operation, *args, **kwargs)
