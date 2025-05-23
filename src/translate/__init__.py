"""
Translation module for converting tweets from Japanese to Korean.
Uses the translation prompt defined in prompts/translate.prompt.
"""
import os
import logging
from typing import Dict, Any, Optional

from anthropic import AsyncAnthropic
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
        model: str = config.common.TRANSLATION_MODEL
) -> str:
    """
    Translate text from Japanese to Korean using the Anthropic API.

    Args:
        text: The Japanese text to translate
        api_key: API key for the Anthropic service (defaults to config.common.ANTHROPIC_API_KEY)
        model: Model name to use for translation (defaults to config.common.TRANSLATION_MODEL)

    Returns:
        The translated Korean text

    Raises:
        TranslationError: If translation fails
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

    # Create Anthropic client and send request
    try:
        client = AsyncAnthropic(api_key=api_key)
        
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

    except Exception as e:
        logger.error(f"Translation failed: {str(e)}")
        raise TranslationError(f"Translation failed: {str(e)}")
