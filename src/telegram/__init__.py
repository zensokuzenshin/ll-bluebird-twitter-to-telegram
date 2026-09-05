import datetime
import logging
from typing import Any

import httpx

import config
import db
import telemetry
from translate.types.translated_tweet import TranslatedTweet
from tweet import Tweet

logger = logging.getLogger(__name__)

# Korea has no DST, so a fixed offset is exact and avoids needing tzdata in the
# runtime image.
KST = datetime.timezone(datetime.timedelta(hours=9), "KST")

_API_BASE = "https://api.telegram.org"


class TelegramError(Exception):
    """Raised when Telegram would not accept a message."""


def _format(tweet: Tweet, text: str) -> str:
    """The author is omitted: each character posts through her own bot."""
    posted_at = tweet.created_at_dt
    when = (
        posted_at.astimezone(KST).strftime("%m/%d %H:%M")
        if posted_at
        else "??/?? ??:??"
    )
    return f"{text}\n\n<code>{when}</code> | <i><a href='{tweet.url}'>Link</a></i>"


async def _send(
    bot_token: str, payload: dict[str, Any], timeout: float = 30.0
) -> dict[str, Any]:
    url = f"{_API_BASE}/bot{bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload)

    if response.status_code != 200:
        raise TelegramError(
            f"sendMessage returned {response.status_code}: {response.text}"
        )

    return response.json()


async def send_telegram_message(tweet: Tweet | TranslatedTweet) -> dict[str, Any]:
    character = config.characters[tweet.author.userName]

    text = (
        await tweet.text_translated()
        if isinstance(tweet, TranslatedTweet)
        else tweet.text
    )
    payload = {
        "chat_id": config.common.TELEGRAM_CHAT_ID,
        "text": _format(tweet, text),
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    if tweet.isReply:
        parent_tg_message_id = await db.get_telegram_message_id_for_tweet(
            tweet.inReplyToId
        )
        if parent_tg_message_id:
            payload["reply_to_message_id"] = parent_tg_message_id

    try:
        response_data = await _send(character.telegram_bot_token, payload)
    except Exception as e:
        telemetry.tweets_forwarded.add(
            1, {"character": character.name, "outcome": "error"}
        )
        logger.error("Failed to send message to Telegram: %s", e)
        await send_error_notification()
        raise

    telemetry.tweets_forwarded.add(1, {"character": character.name, "outcome": "sent"})

    if isinstance(tweet, TranslatedTweet):
        # Recorded so later replies can be threaded under this message. A
        # failure here must not resend it, so it is only logged.
        try:
            telegram_message_id = response_data.get("result", {}).get("message_id")
            if telegram_message_id:
                await db.store_translated_message(
                    telegram_message_id=telegram_message_id,
                    tweet_id=tweet.id,
                    tweet_url=tweet.url,
                    character_name=character.name,
                    translation_text=text,
                    original_text=tweet.text,
                    parent_tweet_id=tweet.inReplyToId,
                    llm_provider=tweet.translation_provider,
                )
                logger.info(
                    "Stored message in database: tweet_id=%s, telegram_message_id=%s",
                    tweet.id,
                    telegram_message_id,
                )
            else:
                logger.warning(
                    "Could not extract message_id from Telegram response: %s",
                    response_data,
                )
        except Exception:
            logger.exception("Failed to store message in database")

    return response_data


async def send_error_notification() -> dict[str, Any] | None:
    """Tell the channel that translations have stalled. Never raises."""
    try:
        return await _send(
            config.characters.mai.telegram_bot_token,
            {
                "chat_id": config.common.TELEGRAM_CHAT_ID,
                "text": (
                    "<b>[시스템 공지]</b>\n\n"
                    "처리 중 오류가 발생하였습니다.\n"
                    "별도 공지 전까지, 번역이 정상적으로 게시되지 않을 수 있습니다.\n"
                ),
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=5.0,
        )
    except Exception as e:
        # Don't retry or re-raise: this is already the error path.
        logger.error("Failed to send error notification: %s", e)
        return None
