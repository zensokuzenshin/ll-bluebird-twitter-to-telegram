"""
Utility functions for retrying database operations with exponential backoff.
"""

import asyncio
import logging
import random
from typing import TypeVar, Callable, Awaitable, Any, Optional, List, Type
import asyncpg

# Configure module-specific logger
logger = logging.getLogger(__name__)

# Type variable for the return type of the retried function
T = TypeVar("T")

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
    asyncpg.exceptions.SerializationError,  # Important for CockroachDB's serializable isolation
    
    # Query-related errors
    asyncpg.exceptions.QueryCanceledError,  # For statement timeout
    
    # CockroachDB-specific retry cases - detected by error message patterns
    # These are raised as generic PostgresError with specific codes/messages
    asyncpg.exceptions.PostgresError,  # Base class for all PostgreSQL errors - filtered by message
)


# CockroachDB-specific error messages that indicate a retry is appropriate
COCKROACHDB_RETRY_MESSAGES = [
    "restart transaction",
    "connection reset by peer",
    "40001",  # Serialization error code
    "SQLSTATE 40001",  # Serialization error code
    "serialization failure",
    "read/write dependencies with inconsistent values",
    "transaction deadline exceeded",
    "transaction aborted",
    "not in a transaction",
    "Transaction waiting for resume",
    "commit result is ambiguous",
    "transaction is too large to complete"
]

def is_retryable_error(e: Exception) -> bool:
    """
    Determine if an exception is retryable, with special handling for CockroachDB errors.
    
    Args:
        e: The exception to check
        
    Returns:
        bool: True if the exception is retryable, False otherwise
    """
    # Check if it's one of our explicitly defined retryable exception types
    if any(isinstance(e, exc_type) for exc_type in DEFAULT_RETRYABLE_EXCEPTIONS if exc_type is not asyncpg.exceptions.PostgresError):
        return True
    
    # For PostgresError, check if it's a CockroachDB-specific error message
    if isinstance(e, asyncpg.exceptions.PostgresError):
        error_str = str(e).lower()
        for retry_msg in COCKROACHDB_RETRY_MESSAGES:
            if retry_msg.lower() in error_str:
                logger.info(f"Detected CockroachDB retryable error: {error_str}")
                return True
    
    return False


async def retry_with_backoff(
    operation: Callable[..., Awaitable[T]],
    *args: Any,
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_backoff: float = DEFAULT_INITIAL_BACKOFF,
    max_backoff: float = DEFAULT_MAX_BACKOFF,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    jitter: float = DEFAULT_JITTER,
    retryable_exceptions: Optional[List[Type[Exception]]] = None,
    **kwargs: Any,
) -> T:
    """
    Retry an async operation with exponential backoff.
    Includes special handling for CockroachDB-specific errors.

    Args:
        operation: The async function to retry
        *args: Positional arguments to pass to the operation
        max_retries: Maximum number of retries
        initial_backoff: Initial backoff time in seconds
        max_backoff: Maximum backoff time in seconds
        backoff_factor: Multiplicative factor for backoff after each retry
        jitter: Random jitter factor to add to backoff (0.0-1.0)
        retryable_exceptions: List of exception types that should trigger a retry
        **kwargs: Keyword arguments to pass to the operation

    Returns:
        The result of the operation

    Raises:
        The last encountered exception if all retries fail
    """
    if retryable_exceptions is None:
        retryable_exceptions = DEFAULT_RETRYABLE_EXCEPTIONS

    retries = 0
    last_exception = None
    
    # Try the operation until it succeeds or we reach max_retries
    while retries <= max_retries:
        try:
            if retries > 0:
                logger.debug(f"Retry attempt {retries}/{max_retries} for operation {operation.__name__}")
            return await operation(*args, **kwargs)
        
        except Exception as e:
            last_exception = e
            
            # Check if this exception is retryable
            if not is_retryable_error(e):
                # Not a retryable exception, reraise immediately
                logger.warning(f"Non-retryable exception in {operation.__name__}: {str(e)}")
                raise
            
            # Check if we've reached max retries
            if retries >= max_retries:
                logger.error(f"Max retries ({max_retries}) reached for {operation.__name__}: {str(e)}")
                raise
            
            # For CockroachDB serialization errors, use a more aggressive retry strategy
            if isinstance(e, asyncpg.exceptions.SerializationError) or (
                isinstance(e, asyncpg.exceptions.PostgresError) and "40001" in str(e)
            ):
                # For serialization failures, use a different backoff strategy
                # CockroachDB docs recommend immediate retry for serialization failures
                # with exponential backoff only after multiple failures
                if retries <= 1:
                    # For first retry, use minimal delay
                    backoff_time = initial_backoff * 0.1
                else:
                    # After that, use normal exponential backoff
                    backoff_time = min(
                        initial_backoff * (backoff_factor ** (retries - 1)),
                        max_backoff
                    )
            else:
                # Normal exponential backoff for other errors
                backoff_time = min(
                    initial_backoff * (backoff_factor ** retries),
                    max_backoff
                )
            
            # Add jitter (random variation) to avoid thundering herd problem
            jitter_amount = backoff_time * jitter * random.uniform(-1, 1)
            final_backoff = max(0.001, backoff_time + jitter_amount)  # Ensure positive backoff
            
            logger.warning(
                f"Retryable error in {operation.__name__}: {str(e)}. "
                f"Retrying in {final_backoff:.3f}s (attempt {retries+1}/{max_retries})"
            )
            
            # Wait before retrying
            await asyncio.sleep(final_backoff)
            
            retries += 1
    
    # We should never reach here due to the raise in the loop, but just in case
    if last_exception:
        raise last_exception
    
    # This should never happen, but needed for type checking
    raise RuntimeError("Unexpected error in retry logic")


async def retry_db_operation(
    operation: Callable[..., Awaitable[T]], 
    *args: Any, 
    **kwargs: Any
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
