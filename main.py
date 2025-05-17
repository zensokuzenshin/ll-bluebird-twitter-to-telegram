import logging
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import httpx
import os
import config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Get environment variables
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY")

# Check for required environment variables
required_vars = {
    "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID
}

missing_vars = [var for var, value in required_vars.items() if not value]
if missing_vars:
    logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
    raise ValueError(f"The following environment variables must be set: {', '.join(missing_vars)}")

TWITTER_API_BASE_URL = "https://api.twitterapi.io"
TWITTER_SEARCH_ENDPOINT = "/twitter/tweet/advanced_search"

# Create FastAPI app instance
app = FastAPI(title="Twitter to Telegram Forwarder")

# Pydantic models for data validation
class Author(BaseModel):
    id: Optional[str] = None
    userName: Optional[str] = None  # Correct field name from logs
    name: Optional[str] = None
    profilePicture: Optional[str] = None
    isBlueVerified: Optional[bool] = None
    followers: Optional[int] = None
    following: Optional[int] = None
    description: Optional[str] = None
    url: Optional[str] = None
    twitterUrl: Optional[str] = None
    
    # Allow additional fields
    class Config:
        extra = "allow"


class Tweet(BaseModel):
    id: Optional[str] = None
    text: Optional[str] = None
    author: Optional[Author] = None
    createdAt: Optional[str] = None  # Correct field name from logs
    retweetCount: Optional[int] = 0  # Correct field name from logs
    likeCount: Optional[int] = 0     # Correct field name from logs
    replyCount: Optional[int] = 0    # Correct field name from logs
    url: Optional[str] = None
    twitterUrl: Optional[str] = None
    viewCount: Optional[int] = None
    quoteCount: Optional[int] = None
    bookmarkCount: Optional[int] = None
    
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
async def send_telegram_message(as_character: config.types.Character, message: str) -> Dict[str, Any]:
    """Send a message to the Telegram chat."""
    url = f"https://api.telegram.org/bot{as_character.telegram_bot_token}/sendMessage"
    
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

    # Get username (now we know the exact field name)
    username = author.userName or "unknown"
    
    name = author.name or username
    tweet_id = tweet.id or ""
    
    # Get tweet text
    text = tweet.text or ""
    
    # Get counts with the correct field names
    reply_count = tweet.replyCount or 0
    retweet_count = tweet.retweetCount or 0
    like_count = tweet.likeCount or 0
    
    # Get or construct URL (prefer twitterUrl if available)
    tweet_url = tweet.twitterUrl or tweet.url or f"https://twitter.com/{username}/status/{tweet_id}"
    
    # Add view count if available
    view_stats = f"👁️ {tweet.viewCount} | " if tweet.viewCount else ""
    
    return (
        f"<b>{name}</b> (@{username})\n\n"
        f"{text}\n\n"
        f"{view_stats}💬 {reply_count} | 🔄 {retweet_count} | ❤️ {like_count}\n"
        f"<a href='{tweet_url}'>View on Twitter</a>"
    )


@app.post("/webhook", status_code=200)
async def receive_webhook(payload: Dict[str, Any]):
    """
    Webhook endpoint to receive Twitter events and forward them to Telegram.
    """
    logger.info("Received webhook payload")
    
    # Log the full payload for debugging
    import json
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
            
            # Extract author information
            if tweet.author:
                author = tweet.author
                logger.info(f"Author: {author.name} (@{author.userName})")
            
            # In debug mode, we're just logging tweets - not forwarding to Telegram
            processed_tweets.append({"id": tweet.id, "processed": True})
            
        except Exception as e:
            logger.error(f"Error processing tweet {i+1}: {str(e)}")
            processed_tweets.append({"error": str(e)})
    
    return {
        "status": "success", 
        "message": f"Processed {len(processed_tweets)} tweets (debug mode)",
        "processed": processed_tweets
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


async def search_tweets(query: str, query_type: str = "Latest", cursor: str = "") -> Dict[str, Any]:
    """
    Search for tweets using the Twitter API's advanced search endpoint.
    
    Args:
        query: Search query string
        query_type: "Latest" or "Top"
        cursor: Pagination cursor
        
    Returns:
        Dictionary containing the search results
    """
    if not TWITTER_API_KEY:
        logger.error("Missing TWITTER_API_KEY environment variable")
        raise ValueError("TWITTER_API_KEY must be set to use the search endpoint")
    
    url = f"{TWITTER_API_BASE_URL}{TWITTER_SEARCH_ENDPOINT}"
    
    params = {
        "query": query,
        "queryType": query_type
    }
    
    if cursor:
        params["cursor"] = cursor
    
    headers = {
        "X-API-Key": TWITTER_API_KEY
    }
    
    logger.info(f"Searching Twitter with query: {query}")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, headers=headers)
            
        if response.status_code != 200:
            logger.error(f"Twitter API error: {response.status_code} - {response.text}")
            raise HTTPException(status_code=response.status_code, detail=f"Twitter API error: {response.text}")
        
        return response.json()
    
    except Exception as e:
        logger.error(f"Error searching Twitter: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error searching Twitter: {str(e)}")


# Direct CLI functions for tweet search and forwarding
async def direct_search_and_forward(
    query: str, 
    query_type: str = "Latest", 
    limit: int = 5,
    forward_to_telegram: bool = True,
    cursor: str = ""
) -> Dict[str, Any]:
    """
    Directly search for tweets using the Twitter API and forward them to Telegram.
    This function bypasses FastAPI and can be called directly.
    
    Args:
        query: Twitter search query (e.g., "from:username", "keyword", etc.)
        query_type: "Latest" or "Top"
        limit: Maximum number of tweets to process
        forward_to_telegram: Whether to forward tweets to Telegram
        cursor: Pagination cursor for retrieving next page of results
        
    Returns:
        Dictionary with results of the operation
    """
    try:
        # Ensure the API key is set
        if not TWITTER_API_KEY:
            logger.error("Missing TWITTER_API_KEY environment variable")
            return {"status": "error", "message": "TWITTER_API_KEY must be set"}
        
        logger.info(f"Searching Twitter with query: {query}")
        
        # Search for tweets
        search_results = await search_tweets(query, query_type, cursor)
        
        # Extract tweets from the response
        tweets = search_results.get("tweets", [])
        
        if not tweets:
            logger.info("No tweets found")
            return {"status": "success", "message": "No tweets found", "count": 0}
        
        logger.info(f"Found {len(tweets)} tweets")
        
        # Limit the number of tweets to process
        tweets = tweets[:limit]
        
        results = []
        
        # Process each tweet
        for i, tweet_data in enumerate(tweets):
            try:
                # Log the raw tweet data structure before parsing
                logger.info(f"Tweet {i+1} raw data structure:")
                logger.info(f"  Keys: {list(tweet_data.keys())}")
                if 'author' in tweet_data and isinstance(tweet_data['author'], dict):
                    logger.info(f"  Author keys: {list(tweet_data['author'].keys())}")
                    
                # Parse the tweet data into our model
                tweet = Tweet.parse_obj(tweet_data)
                
                # Log the tweet text and author info
                logger.info(f"Tweet {i+1}: {tweet.text or 'No text'}")
                
                # Dump the full tweet model for debugging
                if tweet.author:
                    author = tweet.author
                    logger.info(f"Author info - id: {author.id}, name: {author.name}, username fields: {author.userName}")
                
                # Forward to Telegram if enabled
                if forward_to_telegram:
                    formatted_message = format_tweet_for_telegram(tweet)
                    as_character = config.characters[tweet.author.userName]
                    response = await send_telegram_message(as_character, formatted_message)
                    logger.info(f"Successfully forwarded tweet {tweet.id} to Telegram")
                    
                # Store result
                results.append({
                    "tweet_id": tweet.id,
                    "forwarded": forward_to_telegram
                })
                
            except Exception as e:
                logger.error(f"Error processing tweet {i+1}: {str(e)}")
                results.append({"error": str(e)})
        
        return {
            "status": "success",
            "query": query,
            "count": len(results),
            "forwarded": forward_to_telegram,
            "has_next_page": search_results.get("has_next_page", False),
            "next_cursor": search_results.get("next_cursor", ""),
            "results": results
        }
        
    except Exception as e:
        logger.error(f"Error in direct search and forward: {str(e)}")
        return {"status": "error", "message": str(e)}


async def main_cli():
    """Command-line interface for searching tweets and forwarding to Telegram."""
    import sys
    import asyncio
    
    # Check for command-line arguments
    if len(sys.argv) < 2:
        print("Usage: python main.py [--limit=N] [--type=Latest|Top] [--cursor=XYZ] [--no-forward]")
        print("Example: python main.py --limit=3 --type=Latest")
        print("Pagination: python main.py --cursor=abc123")
        return

    query = " OR ".join(f"from:{char.twitter_handle}" for char in config.characters._character_config.values())
    
    # Parse optional arguments
    limit = 5
    query_type = "Latest"
    forward = True
    cursor = ""
    
    for arg in sys.argv[1:]:
        if arg.startswith("--limit="):
            try:
                limit = int(arg.split("=")[1])
            except:
                print(f"Invalid limit value: {arg}")
                return
        elif arg.startswith("--type="):
            query_type = arg.split("=")[1]
            if query_type not in ["Latest", "Top"]:
                print(f"Invalid query type: {query_type}. Must be 'Latest' or 'Top'")
                return
        elif arg.startswith("--cursor="):
            cursor = arg.split("=")[1]
        elif arg == "--no-forward":
            forward = False
    
    # Run the search function
    results = await direct_search_and_forward(
        query=query,
        query_type=query_type,
        limit=limit,
        forward_to_telegram=forward,
        cursor=cursor
    )
    
    # Print results summary
    print(f"\nSearch for: {query}")
    print(f"Found: {results.get('count', 0)} tweets")
    
    if results.get("status") == "success" and results.get("count", 0) > 0:
        print(f"{'Forwarded to Telegram' if forward else 'Tweets found but not forwarded'}")
    else:
        print(f"Error: {results.get('message', 'Unknown error')}")
    
    # Print if there are more results available
    if results.get("has_next_page", False):
        print("More results available. Use the following cursor for pagination:")
        print(f"  --cursor={results.get('next_cursor', '')}")


if __name__ == "__main__":
    # Check if we're in CLI mode or web server mode
    import sys
    
    if len(sys.argv) > 1:
        # CLI mode - direct search without FastAPI
        import asyncio
        asyncio.run(main_cli())
    else:
        # Web server mode - run the FastAPI app
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=8000)
