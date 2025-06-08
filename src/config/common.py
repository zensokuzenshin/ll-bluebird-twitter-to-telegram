import os
from typing import Dict, Any, Optional, Literal, List

# API configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TWITTER_API_BASE_URL = "https://api.twitterapi.io"
TWITTER_SEARCH_ENDPOINT = "/twitter/tweet/advanced_search"
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY")

# Translation settings
DEFAULT_TRANSLATION_MODELS = "anthropic:claude-3-7-sonnet-20250219"
# Parse TRANSLATION_MODELS as a comma-separated list
TRANSLATION_MODELS_STR = os.getenv("TRANSLATION_MODELS", DEFAULT_TRANSLATION_MODELS)
TRANSLATION_MODELS = [model.strip() for model in TRANSLATION_MODELS_STR.split(",")]

# For backward compatibility
DEFAULT_TRANSLATION_MODEL = "claude-3-7-sonnet-20250219"
TRANSLATION_MODEL = os.getenv("TRANSLATION_MODEL", DEFAULT_TRANSLATION_MODEL)
# If TRANSLATION_MODEL is set but TRANSLATION_MODELS isn't explicitly set,
# add it to the list of models to try (at the beginning)
if os.getenv("TRANSLATION_MODEL") and not os.getenv("TRANSLATION_MODELS"):
    TRANSLATION_MODELS.insert(0, f"anthropic:{TRANSLATION_MODEL}")

# Ensure we have at least one model in the list
if not TRANSLATION_MODELS:
    TRANSLATION_MODELS = [f"anthropic:{DEFAULT_TRANSLATION_MODEL}"]

# Error logging configuration
TELEGRAM_ERROR_BOT_TOKEN = os.getenv("TELEGRAM_ERROR_BOT_TOKEN")
TELEGRAM_ERROR_CHAT_ID = os.getenv("TELEGRAM_ERROR_CHAT_ID")
