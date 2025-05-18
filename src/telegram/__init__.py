import httpx
import logging
import os
from typing import Dict, Any
import config

# Configure module-specific logger
logger = logging.getLogger(__name__)

# Get environment variables
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Helper function to send message to Telegram
async def send_telegram_message(as_character: config.types.Character, message: str) -> Dict[str, Any]:
    """Send a message to the Telegram chat."""
    url = f"https://api.telegram.org/bot{as_character.telegram_bot_token}/sendMessage"
    
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,  # Disable link preview
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
        
    if response.status_code != 200:
        logger.error(f"Failed to send message to Telegram: {response.text}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Failed to send message to Telegram")
    
    return response.json()