import asyncio
import os
import sys
from typing import List

import uvicorn
from fastapi import FastAPI, Request, Response

import config
import db
import election
from common import logger
from telegram import send_telegram_message
from translate.types.translated_tweet import TranslatedTweet
from tweet import Tweet, TwitterAPI

# Create FastAPI app instance
app = FastAPI(title="Twitter to Telegram Forwarder")


# Middleware to handle the x-envoy-external-address header
@app.middleware("http")
async def envoy_external_address_middleware(request: Request, call_next):
    # Check if x-envoy-external-address header exists and set it as X-Forwarded-For
    # so Uvicorn's access log will use it
    if "x-envoy-external-address" in request.headers:
        # This is a bit of a hack: We can't modify request.headers directly,
        # but we can modify the underlying scope
        # Remove any existing x-forwarded-for headers
        request.scope["headers"] = [
            (key, value)
            for key, value in request.scope["headers"]
            if key.lower() != b"x-forwarded-for"
        ]
        # Add our x-envoy-external-address as x-forwarded-for
        request.scope["headers"].append(
            (
                b"x-forwarded-for",
                request.headers["x-envoy-external-address"].encode(),
            )
        )

    return await call_next(request)


@app.get("/health")
async def health_check(resp: Response):
    db_healthy, db_error = await db.check_db_connection()
    if not db_healthy:
        resp.status_code = 503
        return {"status": "error"}

    return {"status": "ok"}


async def check_recent_message():
    twitter_client = TwitterAPI()

    while True:
        if not election.is_leader:
            await asyncio.sleep(config.common.LEADER_ELECTION_LEASE_TTL)
            continue

        try:
            # Create list of (most recently posted tweet ~ latest tweet]
            latest_message = await db.get_last_message_tweet_id()
            if latest_message is None:
                raise RuntimeError(
                    "No messages found in database. Killing since this should not happen."
                )

            api_query = (
                "("
                + " OR ".join(
                    f"from:{char.twitter_handle}"
                    for char in config.characters._character_config.values()
                )
                + ")"
                + f" AND since_id:{latest_message}"
            )
            fetched_messages: List[Tweet] = []
            cursor = None
            while True:
                query_result = await twitter_client.advanced_search(
                    api_query, cursor=cursor
                )
                fetched_messages.extend(query_result.tweets)
                cursor = query_result.next_cursor
                if not cursor:
                    break

            # Filter out non-targets, seems like Elon is trolling yet again
            fetched_messages = [
                msg
                for msg in fetched_messages
                if msg.author.userName in config.characters._twitter_handle_map.keys()
            ]

            if len(fetched_messages) == 0:
                wait_duration = config.common.TWITTER_QUERY_INTERVAL_ORDINARY
                logger.info("No new tweets to process.")
                await asyncio.sleep(wait_duration)
                continue

            # We have at least one new tweet to process, change wait duration to a shorter interval
            wait_duration = config.common.TWITTER_QUERY_INTERVAL_ON_MESSAGE
            # sort by date ascending
            messages_to_send: List[Tweet] = [
                TranslatedTweet(**msg.model_dump()) for msg in fetched_messages
            ]
            messages_to_send.sort(key=lambda x: x.created_at_dt)

            for msg in messages_to_send:
                try:
                    await send_telegram_message(msg)
                    logger.info(f"Sent tweet {msg.id} to Telegram.")
                except Exception as e:
                    logger.exception(f"Error processing tweet {msg.id}", exc_info=e)
                    break  # 에러난 부분에서 끊어서 다음 루프에서 다시 시도

            await asyncio.sleep(wait_duration)
        except Exception as e:
            logger.exception(f"Error in check_recent_message loop", exc_info=e)
            await asyncio.sleep(config.common.LEADER_ELECTION_LEASE_TTL)


async def start():
    # Verify current database schema matches our expectations
    expected_version = db.get_expected_schema_version()
    current_version = await db.get_current_schema_version()
    if current_version is None or current_version != expected_version:
        logger.fatal(
            f"Database schema version mismatch, expected {expected_version} but got {current_version}. Exiting."
        )
        sys.exit(1)

    # Start leader election and leader-only background task
    election_task = asyncio.run_coroutine_threadsafe(
        election.start_election(), asyncio.get_running_loop()
    )
    leader_task = asyncio.run_coroutine_threadsafe(
        check_recent_message(), asyncio.get_running_loop()
    )

    # Start FastAPI app
    port = int(os.environ.get("PORT", "8000"))
    uvicorn_config = uvicorn.Config(
        app, host="0.0.0.0", port=port, proxy_headers=True, forwarded_allow_ips="*"
    )
    server = uvicorn.Server(uvicorn_config)

    await server.serve()

    # Shutting down, cleanup
    leader_task.cancel()
    election_task.cancel()


if __name__ == "__main__":
    asyncio.run(start())
