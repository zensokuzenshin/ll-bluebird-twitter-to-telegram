import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import httpx
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Get Telegram API token and chat ID from environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    logger.error("Missing required environment variables: TELEGRAM_BOT_TOKEN and/or TELEGRAM_CHAT_ID")
    raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in the .env file")

# Create FastAPI app instance
app = FastAPI(title="Twitter to Telegram Forwarder")

# Pydantic models for data validation
class Author(BaseModel):
    id: Optional[str] = None
    username: Optional[str] = None
    name: Optional[str] = None
    
    # Allow additional fields
    class Config:
        extra = "allow"


class Tweet(BaseModel):
    id: Optional[str] = None
    text: Optional[str] = None
    author: Optional[Author] = None
    created_at: Optional[str] = None
    retweet_count: Optional[int] = 0
    like_count: Optional[int] = 0
    reply_count: Optional[int] = 0
    url: Optional[str] = None
    
    # Allow additional fields
    class Config:
        extra = "allow"


class WebhookPayload(BaseModel):
    event_type: str = Field(..., description="Type of event, e.g. 'tweet' or 'test_webhook_url'")
    rule_id: Optional[str] = Field(None, description="ID of the rule that triggered this event")
    rule_tag: Optional[str] = Field(None, description="Tag of the rule that triggered this event")
    tweets: Optional[List[Tweet]] = Field(None, description="List of tweets in the payload")
    timestamp: Optional[int] = None
    
    # Allow additional fields that aren't explicitly modeled
    class Config:
        extra = "allow"


# Helper function to send message to Telegram
async def send_telegram_message(message: str) -> Dict[str, Any]:
    """Send a message to the Telegram chat."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
        
    if response.status_code != 200:
        logger.error(f"Failed to send message to Telegram: {response.text}")
        raise HTTPException(status_code=500, detail="Failed to send message to Telegram")
    
    return response.json()


# Format tweet for Telegram
def format_tweet_for_telegram(tweet: Tweet) -> str:
    """Format a tweet for display in Telegram."""
    # Handle potential missing fields
    author = tweet.author or Author()
    username = author.username or "unknown"
    name = author.name or username
    tweet_id = tweet.id or ""
    
    # Get tweet text
    text = tweet.text or ""
    
    # Get counts
    reply_count = tweet.reply_count or 0
    retweet_count = tweet.retweet_count or 0
    like_count = tweet.like_count or 0
    
    # Get or construct URL
    tweet_url = tweet.url or f"https://twitter.com/{username}/status/{tweet_id}"
    
    return (
        f"<b>{name}</b> (@{username})\n\n"
        f"{text}\n\n"
        f"💬 {reply_count} | 🔄 {retweet_count} | ❤️ {like_count}\n"
        f"<a href='{tweet_url}'>View on Twitter</a>"
    )


@app.post("/webhook", status_code=200)
async def receive_webhook(payload: WebhookPayload):
    """
    Webhook endpoint to receive Twitter events and forward them to Telegram.
    """
    logger.info("Received webhook payload")
    
    # Log the full payload for debugging
    import json
    logger.info(f"Full payload JSON: {json.dumps(payload.dict(), indent=2)}")
    
    # Check if this is a test webhook event
    if payload.event_type == "test_webhook_url":
        logger.info("Received test webhook verification event")
        return {"status": "success", "message": "Test webhook received successfully"}
    
    # For actual tweet payloads with event_type 'tweet'
    if payload.event_type == "tweet":
        logger.info(f"Received tweet event with rule tag: {payload.rule_tag or 'unknown'}")
        
        # Log the full payload structure for debugging field names
        payload_dict = payload.dict()
        logger.info(f"Payload keys at root level: {list(payload_dict.keys())}")
        
        # Try to find tweets in the payload
        tweets_list = []
        
        # Check standard location first
        if hasattr(payload, 'tweets') and payload.tweets:
            tweets_list = payload.tweets
            logger.info("Found tweets in the standard 'tweets' field")
        
        # If we didn't find tweets in the standard location, look elsewhere
        if not tweets_list:
            # Log that we're looking in alternative locations
            logger.info("No tweets found in standard location, checking alternative fields")
            
            # Try to access other common fields that might contain tweets
            for field in ['data', 'statuses', 'results']:
                if field in payload_dict and payload_dict[field]:
                    tweets_list = payload_dict[field]
                    logger.info(f"Found potential tweets in '{field}' field")
                    break
        
        if not tweets_list:
            logger.warning("No tweets found in payload")
            return {"status": "skipped", "reason": "No tweets found in payload"}
        
        # For now, just log tweets during debugging instead of forwarding
        logger.info(f"Found {len(tweets_list)} potential tweets")
        
        for i, tweet_data in enumerate(tweets_list):
            # Safely extract tweet data
            if not isinstance(tweet_data, dict):
                logger.warning(f"Tweet {i+1} is not a dictionary, skipping")
                continue
                
            # Log the keys in this tweet object to understand its structure
            logger.info(f"Tweet {i+1} keys: {list(tweet_data.keys())}")
            
            # Try to parse as a Tweet object
            try:
                tweet = Tweet.parse_obj(tweet_data)
                logger.info(f"Tweet {i+1} text: {tweet.text or 'No text available'}")
            except Exception as e:
                logger.warning(f"Error parsing tweet {i+1}: {str(e)}")
        
        return {"status": "success", "message": f"Analyzed {len(tweets_list)} potential tweets (debug mode)"}
    
    # Handle other event types
    logger.warning(f"Unhandled event type: {payload.event_type}")
    return {"status": "received", "message": f"Unhandled event type: {payload.event_type}"}


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
