import asyncio
import contextlib
import datetime
import os
import sys
import time

import uvicorn
from fastapi import FastAPI, Request, Response

import config
import db
import election
import telemetry
from common import logger
from telegram import send_telegram_message
from translate.types.translated_tweet import TranslatedTweet
from tweet import Tweet, TwitterAPI

app = FastAPI(title="Twitter to Telegram Forwarder")

# Sort fallback for a tweet whose timestamp we could not parse
_EPOCH = datetime.datetime.min.replace(tzinfo=datetime.UTC)


@app.middleware("http")
async def envoy_external_address_middleware(request: Request, call_next):
    # Uvicorn's access log reads X-Forwarded-For, which Envoy does not set.
    # Headers are immutable, so the underlying scope has to be rewritten.
    if "x-envoy-external-address" in request.headers:
        request.scope["headers"] = [
            (key, value)
            for key, value in request.scope["headers"]
            if key.lower() != b"x-forwarded-for"
        ]
        request.scope["headers"].append(
            (
                b"x-forwarded-for",
                request.headers["x-envoy-external-address"].encode(),
            )
        )

    return await call_next(request)


@app.get("/health")
async def health_check(resp: Response):
    db_healthy, _ = await db.check_db_connection()
    if not db_healthy:
        resp.status_code = 503
        return {"status": "error"}

    return {"status": "ok"}


async def _fetch_new_tweets(twitter_client: TwitterAPI, since_id: str) -> list[Tweet]:
    """Every tweet from a tracked account posted after `since_id`."""
    api_query = (
        "("
        + " OR ".join(f"from:{char.twitter_handle}" for char in config.characters)
        + ")"
        + f" AND since_id:{since_id}"
    )

    fetched: list[Tweet] = []
    cursor = None
    while True:
        page = await twitter_client.advanced_search(api_query, cursor=cursor)
        fetched.extend(page.tweets or [])
        cursor = page.next_cursor
        # The API hands back a cursor past the last page too, so has_next_page
        # is what actually terminates the walk.
        if not page.has_next_page or not cursor:
            break

    logger.info("Fetched %d new tweets from Twitter API.", len(fetched))

    # `from:` matches more than the accounts asked for, so re-check the author.
    on_target = [
        tweet
        for tweet in fetched
        if (tweet.author.userName or "").lower() in config.characters.twitter_handles
    ]
    logger.info(
        "%d tweets are from target accounts after filtering.",
        len(on_target),
    )

    telemetry.tweets_fetched.add(len(on_target), {"outcome": "on_target"})
    telemetry.tweets_fetched.add(len(fetched) - len(on_target), {"outcome": "filtered"})
    return on_target


async def _poll_once(twitter_client: TwitterAPI) -> bool:
    """One fetch/translate/forward pass. True if there was anything to send."""
    latest_message = await db.get_last_message_tweet_id()
    if latest_message is None:
        raise RuntimeError(
            "No messages found in database. Killing since this should not happen."
        )

    fetched_messages = await _fetch_new_tweets(twitter_client, latest_message)
    if not fetched_messages:
        logger.info("No new tweets to process.")
        return False

    # Oldest first, so replies land after the tweet they answer
    messages_to_send = [TranslatedTweet(**msg.model_dump()) for msg in fetched_messages]
    messages_to_send.sort(key=lambda t: t.created_at_dt or _EPOCH)

    for msg in messages_to_send:
        try:
            await send_telegram_message(msg)
            logger.info("Sent tweet %s to Telegram.", msg.id)
        except Exception:
            logger.exception("Error processing tweet %s", msg.id)
            break  # 에러난 부분에서 끊어서 다음 루프에서 다시 시도

    return True


async def check_recent_message(twitter_client: TwitterAPI) -> None:
    """Leader-only loop: forward every tweet posted since the last one we sent."""
    while True:
        started = time.monotonic()
        try:
            with telemetry.tracer.start_as_current_span("poll_cycle"):
                had_tweets = await _poll_once(twitter_client)
            telemetry.poll_cycle_duration.record(
                time.monotonic() - started, {"outcome": "ok"}
            )

            await asyncio.sleep(
                # Someone is posting, so come back sooner
                config.common.TWITTER_QUERY_INTERVAL_ON_MESSAGE
                if had_tweets
                else config.common.TWITTER_QUERY_INTERVAL_ORDINARY
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error in check_recent_message loop")
            telemetry.poll_cycle_duration.record(
                time.monotonic() - started, {"outcome": "error"}
            )
            await asyncio.sleep(config.common.TWITTER_QUERY_INTERVAL_ON_ERROR)


async def start():
    # Before the first DB/HTTP call, so instrumentation catches it.
    telemetry.setup_opentelemetry()
    telemetry.instrument_fastapi_app(app)

    expected_version = db.get_expected_schema_version()
    current_version = await db.get_current_schema_version()
    if current_version is None or current_version != expected_version:
        logger.fatal(
            f"Database schema version mismatch, expected {expected_version} but got {current_version}. Exiting."
        )
        sys.exit(1)

    # Built here rather than inside the leader task so a missing API key kills
    # the process at startup instead of quietly wedging whichever pod wins.
    twitter_client = TwitterAPI()

    # The election runs check_recent_message while this replica holds the
    # lease and cancels it the moment the lease is lost.
    election_task = asyncio.create_task(
        election.run_forever(lambda: check_recent_message(twitter_client)),
        name="leader-election",
    )

    port = int(os.environ.get("PORT", "8000"))
    uvicorn_config = uvicorn.Config(
        app, host="0.0.0.0", port=port, proxy_headers=True, forwarded_allow_ips="*"
    )
    server = uvicorn.Server(uvicorn_config)

    try:
        await server.serve()
    finally:
        election_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await election_task
        await twitter_client.close()
        await db.close_connection_pool()


if __name__ == "__main__":
    asyncio.run(start())
