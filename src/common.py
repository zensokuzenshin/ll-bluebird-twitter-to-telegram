import logging
import os
import datetime
from typing import Dict, Any
import httpx
import config
from logging_handlers import setup_telegram_logger

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Set up Telegram error logger if credentials are provided
if config.common.TELEGRAM_ERROR_BOT_TOKEN and config.common.TELEGRAM_ERROR_CHAT_ID:
    setup_telegram_logger(
        config.common.TELEGRAM_ERROR_BOT_TOKEN,
        config.common.TELEGRAM_ERROR_CHAT_ID,
        level=logging.ERROR
    )
    logger.info("Telegram error logging is enabled")
else:
    logger.warning("Telegram error logging is disabled - missing bot token or chat ID")

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

# Re-export tweet functionality so existing imports don't break
from tweet import Tweet, Author, WebhookPayload, format_tweet_for_telegram, search_tweets
from telegram import send_telegram_message
from translate import translate, TranslationError

# Direct CLI functions for tweet search and forwarding
async def direct_search_and_forward(
    query: str, 
    query_type: str = "Latest", 
    limit: int = 5,
    forward_to_telegram: bool = True,
    cursor: str = "",
    character_name: str = None
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
        character_name: Name of the character to forward tweets as (if None, tries to determine from query)
        
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
        
        # Sort tweets by date (oldest first) before processing
        try:
            # Create temporary list with (tweet, date) tuples for sorting
            dated_tweets = []
            for tweet in tweets:
                parsed_date = None
                # Try to get parsed date from tweet
                if 'parsed_date' in tweet:
                    parsed_date = tweet['parsed_date']
                # Otherwise try to parse from createdAt
                elif 'createdAt' in tweet:
                    try:
                        parsed_date = datetime.datetime.strptime(
                            tweet['createdAt'],
                            "%a %b %d %H:%M:%S %z %Y"
                        )
                    except (ValueError, TypeError):
                        # If parsing fails, use None (will end up at the end)
                        pass
                dated_tweets.append((tweet, parsed_date))
                
            # Sort by date, with None dates at the end
            # The tuple sort key: (is_none, date_value) ensures None values go last
            sorted_tweets = [t[0] for t in sorted(
                dated_tweets,
                key=lambda x: (x[1] is None, x[1])
            )]
            tweets = sorted_tweets
            logger.info(f"Sorted {len(tweets)} tweets by date (oldest first)")
        except Exception as e:
            logger.warning(f"Failed to sort tweets by date: {str(e)}")
            logger.warning("Will process tweets in their original order")
        
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
                    try:
                        # Try to get character by userName or from specified character_name
                        as_character = None
                        
                        # First try to get character from tweet author username
                        if tweet.author and tweet.author.userName:
                            try:
                                as_character = config.characters[tweet.author.userName]
                                logger.info(f"Found character {as_character.name} for @{tweet.author.userName}")
                            except (KeyError, AttributeError):
                                logger.info(f"No character found for @{tweet.author.userName}")
                        
                        # If no character found and character_name was specified, use that
                        if not as_character and character_name:
                            try:
                                as_character = getattr(config.characters, character_name)
                                logger.info(f"Using specified character: {character_name}")
                            except (AttributeError, KeyError):
                                logger.error(f"Specified character '{character_name}' not found")
                        
                        if as_character:
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
                            
                            # Format and send the tweet (translated if available)
                            try:
                                if translated_text:
                                    # Create a copy of the tweet with translated text
                                    tweet_dict = tweet.dict()
                                    tweet_dict["text"] = translated_text
                                    translated_tweet = Tweet.parse_obj(tweet_dict)
                                    formatted_message = format_tweet_for_telegram(translated_tweet)
                                    
                                    response = await send_telegram_message(as_character, formatted_message)
                                    logger.info(f"Successfully forwarded translated tweet {tweet.id} to Telegram as {as_character.name}")
                                    
                                    # Store success result
                                    results.append({
                                        "tweet_id": tweet.id,
                                        "forwarded": True,
                                        "character": as_character.name,
                                        "translated": True
                                    })
                                else:
                                    # Fall back to original if translation failed
                                    formatted_message = format_tweet_for_telegram(tweet)
                                    response = await send_telegram_message(as_character, formatted_message)
                                    logger.info(f"Successfully forwarded original tweet {tweet.id} to Telegram as {as_character.name} (translation failed)")
                                    
                                    # Store success result
                                    results.append({
                                        "tweet_id": tweet.id,
                                        "forwarded": True,
                                        "character": as_character.name,
                                        "translated": False
                                    })
                            except Exception as e:
                                # Error is already logged in send_telegram_message
                                # Error notification is already sent in send_telegram_message
                                # Just add the result here
                                results.append({
                                    "tweet_id": tweet.id,
                                    "forwarded": False,
                                    "error": f"Failed to send to Telegram: {str(e)}"
                                })
                        else:
                            logger.warning(f"No matching character found for tweet from @{tweet.author.userName if tweet.author else 'unknown'}")
                            results.append({
                                "tweet_id": tweet.id,
                                "forwarded": False,
                                "error": "No matching character found for forwarding"
                            })
                    except Exception as e:
                        logger.error(f"Error forwarding tweet {tweet.id}: {str(e)}")
                        results.append({
                            "tweet_id": tweet.id,
                            "forwarded": False,
                            "error": str(e)
                        })
                else:
                    # Just record the tweet ID if not forwarding
                    results.append({
                        "tweet_id": tweet.id,
                        "forwarded": False
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