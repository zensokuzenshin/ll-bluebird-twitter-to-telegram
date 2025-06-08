import httpx
import logging
from typing import Dict, Any, Optional
import config
from db import store_translated_message, get_telegram_message_id_for_tweet

# Configure module-specific logger
logger = logging.getLogger(__name__)


# Helper function to send message to Telegram
async def send_telegram_message(
    as_character: config.types.Character,
    message: str,
    tweet_id: Optional[str] = None,
    tweet_url: Optional[str] = None,
    original_text: Optional[str] = None,
    translated_text: Optional[str] = None,
    parent_tweet_id: Optional[str] = None,
    llm_provider: Optional[str] = None,
    reply_to_message_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Send a message to the Telegram chat and store it in the database.

    Args:
        as_character: The character to send the message as
        message: The formatted HTML message to send
        tweet_id: The ID of the tweet being forwarded
        tweet_url: The URL of the tweet being forwarded
        original_text: The original tweet text
        translated_text: The translated tweet text
        parent_tweet_id: The ID of the parent tweet if this is a reply
        llm_provider: The LLM provider used for translation
        reply_to_message_id: Telegram message ID to reply to

    Returns:
        Dict[str, Any]: The Telegram API response
    """
    url = f"https://api.telegram.org/bot{as_character.telegram_bot_token}/sendMessage"

    payload = {
        "chat_id": config.common.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,  # Disable link preview
    }

    # If this is a reply to another message, add the reply_to_message_id
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    try:
        # Send the message to Telegram
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload)

        if response.status_code != 200:
            logger.error(f"Failed to send message to Telegram: {response.text}")
            from fastapi import HTTPException

            # Send user-facing error notification
            await send_error_notification()
            raise HTTPException(
                status_code=500, detail="Failed to send message to Telegram"
            )

        # Parse the response
        response_data = response.json()

        # Store the message in the database if we have tweet information
        if tweet_id and tweet_url and original_text and translated_text:
            try:
                telegram_message_id = response_data.get("result", {}).get("message_id")
                if telegram_message_id:
                    # Store the message in the database
                    await store_translated_message(
                        telegram_message_id=telegram_message_id,
                        tweet_id=tweet_id,
                        tweet_url=tweet_url,
                        character_name=as_character.name,
                        translation_text=translated_text,
                        original_text=original_text,
                        parent_tweet_id=parent_tweet_id,
                        llm_provider=llm_provider,
                    )
                    logger.info(
                        f"Stored message in database: tweet_id={tweet_id}, telegram_message_id={telegram_message_id}"
                    )
                else:
                    logger.warning(
                        f"Could not extract message_id from Telegram response: {response_data}"
                    )
            except Exception as db_error:
                # Log but don't fail if database storage fails
                logger.error(f"Failed to store message in database: {str(db_error)}")

        return response_data

    except Exception as e:
        logger.error(f"Exception sending message to Telegram: {str(e)}")
        # Send user-facing error notification
        await send_error_notification()
        from fastapi import HTTPException

        raise HTTPException(
            status_code=500, detail="Failed to send message to Telegram"
        )


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
