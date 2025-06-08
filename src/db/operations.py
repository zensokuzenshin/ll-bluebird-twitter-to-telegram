"""
Database operations for translation-related functionality.
"""

import logging
from typing import List, Dict, Any

from . import get_connection_pool

# Configure module-specific logger
logger = logging.getLogger(__name__)


async def get_reference_translations(
    character_name: str, limit: int = 5
) -> List[Dict[str, Any]]:
    """
    Get previous translations for a character to use as reference for consistent style.

    Args:
        character_name: The character name to get translations for
        limit: Maximum number of translations to return

    Returns:
        List of dictionaries with original and translated text pairs
    """
    pool = await get_connection_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
        SELECT original_text, translation_text
        FROM translated_messages
        WHERE character_name = $1
        ORDER BY created_at DESC
        LIMIT $2
        """,
            character_name,
            limit,
        )

        return [
            {"original": row["original_text"], "translated": row["translation_text"]}
            for row in rows
        ]
