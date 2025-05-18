from fastapi import FastAPI, Request
from typing import Dict, Any
import json
import uvicorn
from starlette.middleware.base import BaseHTTPMiddleware

from common import logger
from tweet import Tweet, format_tweet_for_telegram
from telegram import send_telegram_message
from translate import translate, TranslationError
import config

# Middleware to handle the x-envoy-external-address header
class EnvoyExternalAddressMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Check if x-envoy-external-address header exists and set it as X-Forwarded-For
        # so Uvicorn's access log will use it
        if "x-envoy-external-address" in request.headers:
            # This is a bit of a hack: We can't modify request.headers directly,
            # but we can modify the underlying scope
            
            # Remove any existing x-forwarded-for headers
            request.scope["headers"] = [
                (key, value) for key, value in request.scope["headers"] 
                if key.lower() != b"x-forwarded-for"
            ]
            
            # Add our x-envoy-external-address as x-forwarded-for
            request.scope["headers"].append(
                (b"x-forwarded-for", request.headers["x-envoy-external-address"].encode())
            )
        
        return await call_next(request)

# Create FastAPI app instance
app = FastAPI(title="Twitter to Telegram Forwarder")

# Add the middleware
app.add_middleware(EnvoyExternalAddressMiddleware)

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
        for field in ['data', 'statuses', 'results']:
            if field in payload and isinstance(payload[field], list):
                tweets_list = payload[field]
                logger.info(f"Found {len(tweets_list)} potential tweets in '{field}' field")
                break
    
    # If still no tweets, check if the payload itself is a tweet or array of tweets
    if not tweets_list and "id" in payload and "text" in payload:
        # The payload itself might be a tweet
        tweets_list = [payload]
        logger.info("The payload itself appears to be a single tweet")
    
    if not tweets_list:
        logger.warning("No tweets found in payload")
        return {"status": "skipped", "reason": "No tweets found in payload"}
    
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
                            logger.info(f"Translating tweet to Korean...")
                            translated_text = await translate(original_text)
                            logger.info(f"Translation successful")
                        except TranslationError as e:
                            logger.error(f"Translation error: {str(e)}")
                        except Exception as e:
                            logger.error(f"Unexpected error during translation: {str(e)}")
                    
                    # Format and forward the tweet (translated if available)
                    if translated_text:
                        # Create a copy of the tweet with translated text
                        tweet_dict = tweet.dict()
                        tweet_dict["text"] = translated_text
                        translated_tweet = Tweet.parse_obj(tweet_dict)
                        formatted_message = format_tweet_for_telegram(translated_tweet)
                        
                        await send_telegram_message(character, formatted_message)
                        
                        processed_tweets.append({
                            "id": tweet.id,
                            "forwarded": True,
                            "character": character.name,
                            "translated": True
                        })
                        logger.info(f"Successfully forwarded translated tweet {tweet.id} as {character.name}")
                    else:
                        # Fall back to original if translation failed
                        formatted_message = format_tweet_for_telegram(tweet)
                        await send_telegram_message(character, formatted_message)
                        
                        processed_tweets.append({
                            "id": tweet.id,
                            "forwarded": True,
                            "character": character.name,
                            "translated": False
                        })
                        logger.info(f"Successfully forwarded original tweet {tweet.id} as {character.name} (translation failed)")
                except (KeyError, AttributeError):
                    logger.warning(f"No matching character found for @{author_username}")
                    processed_tweets.append({
                        "id": tweet.id,
                        "forwarded": False,
                        "reason": "No matching character found"
                    })
            else:
                logger.warning(f"Tweet {i+1} has no author or username")
                processed_tweets.append({
                    "id": tweet.id if tweet.id else f"unknown-{i}",
                    "forwarded": False,
                    "reason": "Missing author information"
                })
            
        except Exception as e:
            logger.error(f"Error processing tweet {i+1}: {str(e)}")
            processed_tweets.append({"error": str(e)})
    
    return {
        "status": "success", 
        "message": f"Processed {len(processed_tweets)} tweets",
        "processed": processed_tweets
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
        forwarded_allow_ips="*"  # Trust X-Forwarded-* headers from all IPs
    )