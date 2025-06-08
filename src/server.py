from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from typing import Dict, Any
import json
import uvicorn
import datetime
from starlette.middleware.base import BaseHTTPMiddleware

from common import logger
from tweet import Tweet, format_tweet_for_telegram
from telegram import send_telegram_message
from translate import translate, TranslationError
import config
from db import (
    get_connection_pool,
    close_connection_pool,
    get_telegram_message_id_for_tweet,
)

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize the database connection pool on startup and verify schema version."""
    try:
        logger.info("Initializing database connection pool...")

        # Initialize connection pool
        await get_connection_pool()
        logger.info("Database connection pool initialized successfully")

        # Check database schema version - do NOT run migrations automatically
        from db import check_schema_version

        schema_valid = await check_schema_version()
        if not schema_valid:
            logger.error("Database schema version mismatch - shutting down server")
            logger.error("Please run migrations manually with: python src/cli.py migrate-db")
            # Exit with error code to indicate that the server should not start
            import sys
            sys.exit(1)

        logger.info("Database schema version verified successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {str(e)}")
        # Exit with error code
        import sys
        logger.error("Database initialization failed - shutting down server")
        sys.exit(1)

    yield

    """Close the database connection pool on shutdown."""
    logger.info("Closing database connection pool...")
    await close_connection_pool()
    logger.info("Database connection pool closed")


# Create FastAPI app instance
app = FastAPI(title="Twitter to Telegram Forwarder", lifespan=lifespan)

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

@app.post("/webhook", status_code=200)
async def receive_webhook(payload: Dict[str, Any], request: Request):
    """
    Webhook endpoint to receive Twitter events and forward them to Telegram.
    """
    # Get client IP - prefer x-envoy-external-address header if it exists
    client_ip = request.headers.get("x-envoy-external-address", request.client.host)
    logger.info("Received webhook payload")

    # Log the full payload for debugging
    logger.info(f"Full payload JSON: {json.dumps(payload, indent=2)}")

    # Log root level keys to understand structure
    logger.info(f"Payload keys at root level: {list(payload.keys())}")

    # Check if this is a test webhook event
    if payload.get("event_type") == "test_webhook_url":
        logger.info("Received test webhook verification event")
        return {"status": "success", "message": "Test webhook received successfully"}

    # Check for tweets array directly in the payload
    tweets_list = []

    # Try to locate tweets in the payload
    if "tweets" in payload and isinstance(payload["tweets"], list):
        tweets_list = payload["tweets"]
        logger.info(f"Found {len(tweets_list)} tweets in 'tweets' field")

    # If no tweets found, look in other common locations
    if not tweets_list:
        for field in ["data", "statuses", "results"]:
            if field in payload and isinstance(payload[field], list):
                tweets_list = payload[field]
                logger.info(
                    f"Found {len(tweets_list)} potential tweets in '{field}' field"
                )
                break

    # If still no tweets, check if the payload itself is a tweet or array of tweets
    if not tweets_list and "id" in payload and "text" in payload:
        # The payload itself might be a tweet
        tweets_list = [payload]
        logger.info("The payload itself appears to be a single tweet")

    if not tweets_list:
        logger.warning("No tweets found in payload")
        return {"status": "skipped", "reason": "No tweets found in payload"}

    # Sort tweets by date (oldest first) before processing
    try:
        logger.info("Sorting tweets by date (oldest first)...")

        # Create temporary list with (tweet, date) tuples for sorting
        dated_tweets = []
        for tweet_data in tweets_list:
            if not isinstance(tweet_data, dict):
                # Skip non-dictionary entries
                dated_tweets.append((tweet_data, None))
                continue

            parsed_date = None
            # Try to get parsed date from tweet
            if "parsed_date" in tweet_data:
                parsed_date = tweet_data["parsed_date"]
            # Otherwise try to parse from createdAt
            elif "createdAt" in tweet_data:
                try:
                    parsed_date = datetime.datetime.strptime(
                        tweet_data["createdAt"], "%a %b %d %H:%M:%S %z %Y"
                    )
                except (ValueError, TypeError):
                    # If parsing fails, use None (will end up at the end)
                    pass
            dated_tweets.append((tweet_data, parsed_date))

        # Sort by date, with None dates at the end
        # The tuple sort key: (is_none, date_value) ensures None values go last
        sorted_tweets = [
            t[0] for t in sorted(dated_tweets, key=lambda x: (x[1] is None, x[1]))
        ]
        tweets_list = sorted_tweets
        logger.info(f"Sorted {len(tweets_list)} tweets by date (oldest first)")
    except Exception as e:
        logger.warning(f"Failed to sort tweets by date: {str(e)}")
        logger.warning("Will process tweets in their original order")

    # Process each tweet
    processed_tweets = []

    for i, tweet_data in enumerate(tweets_list):
        if not isinstance(tweet_data, dict):
            logger.warning(f"Tweet {i+1} is not a dictionary, skipping")
            continue

        # Log the keys in this tweet object
        logger.info(f"Tweet {i+1} keys: {list(tweet_data.keys())}")

        try:
            # Parse the tweet data
            tweet = Tweet.parse_obj(tweet_data)
            logger.info(f"Tweet {i+1} text: {tweet.text or 'No text available'}")

            # Extract author information for matching with character
            if tweet.author and tweet.author.userName:
                author_username = tweet.author.userName.lower()
                logger.info(f"Author: {tweet.author.name} (@{author_username})")

                # Try to find matching character for the tweet
                try:
                    character = config.characters[author_username]
                    logger.info(f"Found matching character: {character.name}")

                    # Always translate the tweet
                    original_text = tweet.text or ""
                    translated_text = None

                    if original_text:
                        try:
                            logger.info("Translating tweet to Korean...")
                            translated_text = await translate(original_text)
                            logger.info("Translation successful")
                        except TranslationError as e:
                            logger.error(f"Translation error: {str(e)}")
                        except Exception as e:
                            logger.error(
                                f"Unexpected error during translation: {str(e)}"
                            )

                    # Check if this is a reply to another tweet
                    reply_to_message_id = None
                    if tweet.inReplyToId:
                        logger.info(
                            f"Tweet {tweet.id} is a reply to tweet {tweet.inReplyToId}"
                        )
                        # Try to find the Telegram message ID for the parent tweet
                        try:
                            parent_telegram_message_id = (
                                await get_telegram_message_id_for_tweet(
                                    tweet.inReplyToId
                                )
                            )
                            if parent_telegram_message_id:
                                logger.info(
                                    f"Found parent Telegram message ID: {parent_telegram_message_id}"
                                )
                                reply_to_message_id = parent_telegram_message_id
                            else:
                                logger.info(
                                    f"No Telegram message found for parent tweet {tweet.inReplyToId}"
                                )
                        except Exception as e:
                            logger.error(f"Error looking up parent tweet: {str(e)}")

                    # Get the tweet URL (original or constructed)
                    tweet_url = (
                        tweet.twitterUrl
                        or tweet.url
                        or f"https://twitter.com/{author_username}/status/{tweet.id}"
                    )

                    # Format and forward the tweet (translated if available)
                    try:
                        if translated_text:
                            # Create a copy of the tweet with translated text
                            tweet_dict = tweet.dict()
                            tweet_dict["text"] = translated_text
                            translated_tweet = Tweet.parse_obj(tweet_dict)
                            formatted_message = format_tweet_for_telegram(
                                translated_tweet
                            )

                            # Send message with full context for database storage
                            await send_telegram_message(
                                as_character=character,
                                message=formatted_message,
                                tweet_id=tweet.id,
                                tweet_url=tweet_url,
                                original_text=original_text,
                                translated_text=translated_text,
                                parent_tweet_id=tweet.inReplyToId,
                                llm_provider=(
                                    config.common.TRANSLATION_MODELS[0]
                                    if config.common.TRANSLATION_MODELS
                                    else None
                                ),
                                reply_to_message_id=reply_to_message_id,
                            )

                            processed_tweets.append(
                                {
                                    "id": tweet.id,
                                    "forwarded": True,
                                    "character": character.name,
                                    "translated": True,
                                    "is_reply": bool(reply_to_message_id),
                                }
                            )
                            logger.info(
                                f"Successfully forwarded translated tweet {tweet.id} as {character.name}"
                            )
                        else:
                            # Fall back to original if translation failed
                            formatted_message = format_tweet_for_telegram(tweet)

                            # Send message with full context for database storage
                            await send_telegram_message(
                                as_character=character,
                                message=formatted_message,
                                tweet_id=tweet.id,
                                tweet_url=tweet_url,
                                original_text=original_text,
                                translated_text=original_text,  # Use original as translation failed
                                parent_tweet_id=tweet.inReplyToId,
                                reply_to_message_id=reply_to_message_id,
                            )

                            processed_tweets.append(
                                {
                                    "id": tweet.id,
                                    "forwarded": True,
                                    "character": character.name,
                                    "translated": False,
                                    "is_reply": bool(reply_to_message_id),
                                }
                            )
                            logger.info(
                                f"Successfully forwarded original tweet {tweet.id} as {character.name} (translation failed)"
                            )
                    except Exception as e:
                        # Error and user notification are already handled in send_telegram_message
                        logger.error(f"Error sending tweet to Telegram: {str(e)}")
                        processed_tweets.append(
                            {
                                "id": tweet.id,
                                "forwarded": False,
                                "character": character.name,
                                "error": "Message delivery failed",
                            }
                        )
                except (KeyError, AttributeError):
                    logger.warning(
                        f"No matching character found for @{author_username}"
                    )
                    processed_tweets.append(
                        {
                            "id": tweet.id,
                            "forwarded": False,
                            "reason": "No matching character found",
                        }
                    )
            else:
                logger.warning(f"Tweet {i+1} has no author or username")
                processed_tweets.append(
                    {
                        "id": tweet.id if tweet.id else f"unknown-{i}",
                        "forwarded": False,
                        "reason": "Missing author information",
                    }
                )

        except Exception as e:
            logger.error(f"Error processing tweet {i+1}: {str(e)}")
            processed_tweets.append({"error": str(e)})

    return {
        "status": "success",
        "message": f"Processed {len(processed_tweets)} tweets",
        "processed": processed_tweets,
    }


@app.get("/health")
async def health_check(request: Request):
    """Health check endpoint."""
    client_ip = request.headers.get("x-envoy-external-address", request.client.host)
    return {"status": "ok", "client_ip": client_ip}


if __name__ == "__main__":
    # Run the FastAPI app with proxy headers support
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        proxy_headers=True,  # Enable proxy headers handling
        forwarded_allow_ips="*",  # Trust X-Forwarded-* headers from all IPs
    )
