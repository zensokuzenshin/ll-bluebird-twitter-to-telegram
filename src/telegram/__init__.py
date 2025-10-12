import datetime
import logging
from typing import Any, Dict, Optional, Union

import httpx

import config
import db
from translate.types.translated_tweet import TranslatedTweet
from tweet import Tweet

# Configure module-specific logger
logger = logging.getLogger(__name__)


# Helper function to send message to Telegram
async def send_telegram_message(
    tweet: Union[Tweet, TranslatedTweet],
) -> Dict[str, Any]:
    # Find matching character and build API URL
    character = config.characters[tweet.author.userName]
    url = f"https://api.telegram.org/bot{character.telegram_bot_token}/sendMessage"

    payload = {
        "chat_id": config.common.TELEGRAM_CHAT_ID,
        "text": (
            f"{await tweet.text_translated if isinstance(tweet, TranslatedTweet) else tweet.text}\n\n"
            f"<code>{(tweet.created_at_dt + datetime.timedelta(hours=9)).strftime('%m/%d %H:%M')}</code> | <i><a href='{tweet.url}'>Link</a></i>"
        ),
        "parse_mode": "HTML",
        "disable_web_page_preview": True,  # Disable link preview
    }

    if tweet.isReply:
        parent_tg_message_id = await db.get_telegram_message_id_for_tweet(
            tweet.inReplyToId
        )
        if parent_tg_message_id:
            payload["reply_to_message_id"] = parent_tg_message_id

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

        if isinstance(tweet, TranslatedTweet):
            # Store the message in the database if we have tweet information
            try:
                telegram_message_id = response_data.get("result", {}).get("message_id")
                if telegram_message_id:
                    # Store the message in the database
                    await db.store_translated_message(
                        telegram_message_id=telegram_message_id,
                        tweet_id=tweet.id,
                        tweet_url=tweet.url,
                        character_name=character.name,
                        translation_text=await tweet.text_translated,
                        original_text=tweet.text,
                        parent_tweet_id=tweet.inReplyToId,
                        llm_provider=tweet.translation_provider,
                    )
                    logger.info(
                        f"Stored message in database: tweet_id={tweet.id}, telegram_message_id={telegram_message_id}"
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
