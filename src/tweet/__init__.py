from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any
import datetime
import httpx
import os
import logging
import config


# Configure module-specific logger
logger = logging.getLogger(__name__)


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
    createdAt: Optional[str] = None  # Original string format from Twitter API
    parsed_date: Optional[datetime.datetime] = None  # Parsed datetime object
    retweetCount: Optional[int] = 0  # Correct field name from logs
    likeCount: Optional[int] = 0  # Correct field name from logs
    replyCount: Optional[int] = 0  # Correct field name from logs
    url: Optional[str] = None
    twitterUrl: Optional[str] = None
    viewCount: Optional[int] = None
    quoteCount: Optional[int] = None
    bookmarkCount: Optional[int] = None
    inReplyToId: Optional[str] = None  # ID of the tweet this is replying to
    inReplyToUserId: Optional[str] = None  # ID of the user this is replying to

    # Allow additional fields
    class Config:
        extra = "allow"

    @validator("parsed_date", pre=True, always=True)
    def parse_date(cls, v, values):
        """Parse the date from createdAt field."""
        if v is not None:
            # If already parsed, just return it
            return v

        # Try to parse from createdAt
        created_at = values.get("createdAt")
        if not created_at:
            return None

        try:
            # Twitter date format: "Thu May 15 23:21:00 +0000 2025"
            # Use strptime to parse it
            date_obj = datetime.datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
            return date_obj
        except (ValueError, TypeError):
            # If parsing fails, return None
            return None


class WebhookPayload(BaseModel):
    event_type: str = Field(
        ..., description="Type of event, e.g. 'tweet' or 'test_webhook_url'"
    )
    rule_id: Optional[str] = Field(
        None, description="ID of the rule that triggered this event"
    )
    rule_tag: Optional[str] = Field(
        None, description="Tag of the rule that triggered this event"
    )
    tweets: Optional[List[Tweet]] = Field(
        None, description="List of tweets in the payload"
    )
    timestamp: Optional[int] = None

    # Allow additional fields that aren't explicitly modeled
    class Config:
        extra = "allow"


# Format tweet for Telegram
def format_tweet_for_telegram(tweet: Tweet) -> str:
    """Format a tweet for display in Telegram."""
    # Handle potential missing fields
    author = tweet.author or Author()

    # Get username for constructing URL if needed
    username = author.userName or "unknown"
    tweet_id = tweet.id or ""

    # Get tweet text
    text = tweet.text or ""

    # Get or construct URL (prefer twitterUrl if available)
    tweet_url = (
        tweet.twitterUrl
        or tweet.url
        or f"https://twitter.com/{username}/status/{tweet_id}"
    )

    # Format the date (KST = UTC+9)
    date_str = ""
    if tweet.parsed_date:
        try:
            # Convert to KST by adding 9 hours
            kst_date = tweet.parsed_date + datetime.timedelta(hours=9)

            # Format as MM.DD. hh:mm
            date_str = kst_date.strftime("%m/%d %H:%M")
        except Exception:
            # If date formatting fails, use empty string
            date_str = ""

    # Simple format with text, date, and link
    # Use Telegram's HTML formatting - limited but supported
    return (
        f"{text}\n\n" f"<code>{date_str}</code> | <i><a href='{tweet_url}'>Link</a></i>"
    )


async def search_tweets(
    query: str, query_type: str = "Latest", cursor: str = ""
) -> Dict[str, Any]:
    """
    Search for tweets using the Twitter API's advanced search endpoint.

    Args:
        query: Search query string
        query_type: "Latest" or "Top"
        cursor: Pagination cursor

    Returns:
        Dictionary containing the search results
    """
    if not config.common.TWITTER_API_KEY:
        logger.error("Missing TWITTER_API_KEY environment variable")
        raise ValueError("TWITTER_API_KEY must be set to use the search endpoint")

    url = f"{config.common.TWITTER_API_BASE_URL}{config.common.TWITTER_SEARCH_ENDPOINT}"

    params = {"query": query, "queryType": query_type}

    if cursor:
        params["cursor"] = cursor

    headers = {"X-API-Key": config.common.TWITTER_API_KEY}

    # Add cursor info to log
    cursor_info = f", cursor: {cursor}" if cursor else ""
    logger.info(f"Searching Twitter with query: {query}{cursor_info}")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, headers=headers)

        if response.status_code != 200:
            logger.error(f"Twitter API error: {response.status_code} - {response.text}")
            from fastapi import HTTPException

            raise HTTPException(
                status_code=response.status_code,
                detail=f"Twitter API error: {response.text}",
            )

        # Parse JSON and log pagination info
        result = response.json()

        # Log pagination details
        has_next = result.get("has_next_page", False)
        next_cursor = result.get("next_cursor", "")
        tweet_count = len(result.get("tweets", []))

        logger.info(
            f"Search returned {tweet_count} tweets, has_next_page: {has_next}, next_cursor: {next_cursor}"
        )

        return result

    except Exception as e:
        logger.error(f"Error searching Twitter: {str(e)}")
        from fastapi import HTTPException

        raise HTTPException(
            status_code=500, detail=f"Error searching Twitter: {str(e)}"
        )
