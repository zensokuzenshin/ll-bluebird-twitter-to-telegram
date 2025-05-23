import os
from typing import Dict, Any, Optional

# API configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TWITTER_API_BASE_URL = "https://api.twitterapi.io"
TWITTER_SEARCH_ENDPOINT = "/twitter/tweet/advanced_search"
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY")

# Translation settings
DEFAULT_TRANSLATION_MODEL = "claude-3-7-sonnet-20250219"
TRANSLATION_MODEL = os.getenv("TRANSLATION_MODEL", DEFAULT_TRANSLATION_MODEL)

# Error logging configuration
TELEGRAM_ERROR_BOT_TOKEN = os.getenv("TELEGRAM_ERROR_BOT_TOKEN")
TELEGRAM_ERROR_CHAT_ID = os.getenv("TELEGRAM_ERROR_CHAT_ID")
