import httpx
import logging
from typing import Dict, Any, Optional
import config

# Configure module-specific logger
logger = logging.getLogger(__name__)


# Helper function to send message to Telegram
async def send_telegram_message(as_character: config.types.Character, message: str) -> Dict[str, Any]:
    """Send a message to the Telegram chat."""
    url = f"https://api.telegram.org/bot{as_character.telegram_bot_token}/sendMessage"
    
    payload = {
        "chat_id": config.common.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,  # Disable link preview
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload)
            
        if response.status_code != 200:
            logger.error(f"Failed to send message to Telegram: {response.text}")
            from fastapi import HTTPException
            # Send user-facing error notification
            await send_error_notification()
            raise HTTPException(status_code=500, detail="Failed to send message to Telegram")
        
        return response.json()
    except Exception as e:
        logger.error(f"Exception sending message to Telegram: {str(e)}")
        # Send user-facing error notification
        await send_error_notification()
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Failed to send message to Telegram")

async def send_error_notification() -> Optional[Dict[str, Any]]:
    try:
        error_message = (
            "<b>[시스템 공지]</b>\n\n"
            "처리 중 오류가 발생하였습니다.\n"
            "별도 공지 전까지, 번역이 정상적으로 게시되지 않을 수 있습니다.\n"
        )
        
        # Send the error notification
        url = f"https://api.telegram.org/bot{config.characters.mai.telegram_bot_token}/sendMessage"
        
        payload = {
            "chat_id": config.common.TELEGRAM_CHAT_ID,
            "text": error_message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(url, json=payload)
            
        if response.status_code != 200:
            logger.error(f"Failed to send error notification: {response.text}")
            return None
            
        logger.info("User-facing error notification sent successfully")
        return response.json()
        
    except Exception as e:
        # If error notification itself fails, just log it but don't retry or raise
        # to avoid potential infinite loops
        logger.error(f"Failed to send error notification: {str(e)}")
        return None
