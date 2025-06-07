"""
Translation module for converting tweets from Japanese to Korean.
Uses the translation prompt defined in prompts/translate.prompt.
"""
import os
import logging
from typing import Dict, Any, Optional
import asyncio
import random

from anthropic import AsyncAnthropic, RateLimitError, APIStatusError, APIError
from anthropic.types import MessageParam

import config

# Configure logging
logger = logging.getLogger(__name__)


class TranslationError(Exception):
    """Exception raised for errors during translation."""
    pass


async def translate(
        text: str,
        api_key: Optional[str] = None,
        model: str = config.common.TRANSLATION_MODEL,
        max_retries: int = 3,
        initial_backoff: float = 1.0
) -> str:
    """
    Translate text from Japanese to Korean using the Anthropic API.

    Args:
        text: The Japanese text to translate
        api_key: API key for the Anthropic service (defaults to config.common.ANTHROPIC_API_KEY)
        model: Model name to use for translation (defaults to config.common.TRANSLATION_MODEL)
        max_retries: Maximum number of retry attempts for rate limit errors (default: 3)
        initial_backoff: Initial backoff time in seconds (default: 1.0)

    Returns:
        The translated Korean text

    Raises:
        TranslationError: If translation fails after all retry attempts
    """
    # Validate inputs
    if not text or not text.strip():
        return ""

    # Get API key from config if not provided
    if not api_key:
        api_key = config.common.ANTHROPIC_API_KEY
        if not api_key:
            raise TranslationError("No API key provided. Set ANTHROPIC_API_KEY environment variable or pass api_key.")
            
    # Log which model we're using
    logger.info(f"Translating text using model: {model}")

    # Load translation prompt
    try:
        prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "prompts",
            "translate.prompt"
        )

        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt_template = f.read()

        # Fill in the template with the text to translate
        prompt = prompt_template.replace("{{TEXT}}", text)

    except Exception as e:
        logger.error(f"Failed to load translation prompt: {str(e)}")
        raise TranslationError(f"Failed to load translation prompt: {str(e)}")

    # Create Anthropic client
    client = AsyncAnthropic(api_key=api_key)
    
    # Initialize retry parameters
    retry_count = 0
    backoff_time = initial_backoff
    
    while True:
        try:
            message = await client.messages.create(
                model=model,
                max_tokens=1024,
                messages=[
                    MessageParam(role="user", content=prompt)
                ]
            )
            
            # Extract the translated text from the response
            if not message.content:
                logger.error("No content in response")
                raise TranslationError("No translation returned from API")
            
            # Get the text from the first content block
            for content_block in message.content:
                if content_block.type == "text":
                    return content_block.text
            
            # If we didn't find any text blocks
            logger.error("No text content in response")
            raise TranslationError("No translation text in response")

        except RateLimitError as e:
            # This is a specific rate limit error (429), we can retry
            if retry_count < max_retries:
                retry_count += 1
                logger.warning(
                    f"Rate limit error from Anthropic API (429). Retrying ({retry_count}/{max_retries}) "
                    f"in {backoff_time:.2f} seconds..."
                )
                
                # Exponential backoff with jitter
                jitter = random.uniform(0.8, 1.2)  # ±20% jitter
                await asyncio.sleep(backoff_time * jitter)
                
                # Increase backoff for next attempt (exponential)
                backoff_time *= 2
            else:
                # We've exhausted retries
                logger.error(f"Translation failed after {retry_count} retries due to rate limits: {str(e)}")
                raise TranslationError(f"Translation failed due to rate limits: {str(e)}")
                
        except APIStatusError as e:
            # Check if this is a rate limit error (HTTP 429)
            if e.status_code == 429 and retry_count < max_retries:
                retry_count += 1
                logger.warning(
                    f"Rate limit error from Anthropic API (HTTP 429). Retrying ({retry_count}/{max_retries}) "
                    f"in {backoff_time:.2f} seconds..."
                )
                
                # Exponential backoff with jitter
                jitter = random.uniform(0.8, 1.2)  # ±20% jitter
                await asyncio.sleep(backoff_time * jitter)
                
                # Increase backoff for next attempt (exponential)
                backoff_time *= 2
            else:
                # Either not a rate limit error or we've exhausted retries
                logger.error(f"API error with status code {e.status_code}: {str(e)}")
                raise TranslationError(f"Translation failed with API error (status {e.status_code}): {str(e)}")
        
        except Exception as e:
            # Not a rate limit error, don't retry
            logger.error(f"Translation failed with non-retryable error: {str(e)}")
            raise TranslationError(f"Translation failed: {str(e)}")
