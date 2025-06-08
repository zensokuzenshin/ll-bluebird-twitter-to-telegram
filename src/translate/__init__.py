"""
Translation module for converting tweets from Japanese to Korean.
Uses the translation prompt defined in prompts/translate.prompt.
Supports multiple LLM providers with fallback and retry logic.
"""

import os
import logging
from typing import Dict, Any, Optional, List, Tuple, Protocol, Union
import asyncio
import random
from abc import ABC, abstractmethod

# Import for Anthropic provider
try:
    from anthropic import AsyncAnthropic, RateLimitError as AnthropicRateLimitError
    from anthropic import (
        APIStatusError as AnthropicAPIStatusError,
        APIError as AnthropicAPIError,
    )
    from anthropic.types import MessageParam

    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

# Import for OpenAI provider
try:
    from openai import AsyncOpenAI
    from openai.types.chat import ChatCompletionMessageParam
    from openai import RateLimitError as OpenAIRateLimitError
    from openai import (
        APIStatusError as OpenAIAPIStatusError,
        APIError as OpenAIAPIError,
    )

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

import config

# Configure logging
logger = logging.getLogger(__name__)


class TranslationError(Exception):
    """Exception raised for errors during translation."""

    pass


class RateLimitedError(TranslationError):
    """Exception raised when API rate limits are hit."""

    pass


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def translate(
        self,
        text: str,
        prompt_template: str,
        max_retries: int = 3,
        initial_backoff: float = 1.0,
    ) -> str:
        """Translate text using the LLM provider."""
        pass

    @classmethod
    def create(cls, provider_name: str, model_name: str) -> Optional["LLMProvider"]:
        """Factory method to create the appropriate LLM provider."""
        if provider_name.lower() == "anthropic" and ANTHROPIC_AVAILABLE:
            return AnthropicProvider(model_name)
        elif provider_name.lower() == "openai" and OPENAI_AVAILABLE:
            return OpenAIProvider(model_name)
        return None


class AnthropicProvider(LLMProvider):
    """Anthropic Claude LLM provider."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.api_key = config.common.ANTHROPIC_API_KEY
        if not self.api_key:
            raise TranslationError(
                "No Anthropic API key provided. Set ANTHROPIC_API_KEY environment variable."
            )

    async def translate(
        self,
        text: str,
        prompt_template: str,
        max_retries: int = 3,
        initial_backoff: float = 1.0,
    ) -> str:
        """
        Translate text using Anthropic's Claude API.

        Args:
            text: The text to translate
            prompt_template: The prompt template to use
            max_retries: Maximum number of retry attempts for rate limit errors
            initial_backoff: Initial backoff time in seconds

        Returns:
            The translated text

        Raises:
            TranslationError: If translation fails after all retry attempts
            RateLimitedError: If rate limits are hit and retries are exhausted
        """
        if not ANTHROPIC_AVAILABLE:
            raise TranslationError(
                "Anthropic package is not installed. Install with 'pip install anthropic'."
            )

        # Create Anthropic client
        client = AsyncAnthropic(api_key=self.api_key)

        # Fill in the template with the text to translate
        prompt = prompt_template.replace("{{TEXT}}", text)

        # Initialize retry parameters
        retry_count = 0
        backoff_time = initial_backoff

        while True:
            try:
                logger.info(
                    f"Translating text using Anthropic model: {self.model_name}"
                )

                message = await client.messages.create(
                    model=self.model_name,
                    max_tokens=1024,
                    messages=[MessageParam(role="user", content=prompt)],
                )

                # Extract the translated text from the response
                if not message.content:
                    logger.error("No content in Anthropic response")
                    raise TranslationError("No translation returned from Anthropic API")

                # Get the text from the first content block
                for content_block in message.content:
                    if content_block.type == "text":
                        return content_block.text

                # If we didn't find any text blocks
                logger.error("No text content in Anthropic response")
                raise TranslationError("No translation text in Anthropic response")

            except (AnthropicRateLimitError, AnthropicAPIStatusError) as e:
                # Check if this is a rate limit error (either direct RateLimitError or status code 429)
                is_rate_limit = isinstance(e, AnthropicRateLimitError) or (
                    isinstance(e, AnthropicAPIStatusError) and e.status_code == 429
                )

                if is_rate_limit and retry_count < max_retries:
                    retry_count += 1
                    logger.warning(
                        f"Rate limit error from Anthropic API. Retrying ({retry_count}/{max_retries}) "
                        f"in {backoff_time:.2f} seconds..."
                    )

                    # Exponential backoff with jitter
                    jitter = random.uniform(0.8, 1.2)  # ±20% jitter
                    await asyncio.sleep(backoff_time * jitter)

                    # Increase backoff for next attempt (exponential)
                    backoff_time *= 2
                elif is_rate_limit:
                    # We've exhausted retries for rate limits
                    logger.error(
                        f"Anthropic translation failed after {retry_count} retries due to rate limits: {str(e)}"
                    )
                    raise RateLimitedError(
                        f"Anthropic translation failed due to rate limits: {str(e)}"
                    )
                else:
                    # Not a rate limit error
                    logger.error(f"Anthropic API error: {str(e)}")
                    raise TranslationError(
                        f"Anthropic translation failed with API error: {str(e)}"
                    )

            except Exception as e:
                # Not a rate limit error, don't retry
                logger.error(
                    f"Anthropic translation failed with non-retryable error: {str(e)}"
                )
                raise TranslationError(f"Anthropic translation failed: {str(e)}")


class OpenAIProvider(LLMProvider):
    """OpenAI GPT LLM provider."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.api_key = config.common.OPENAI_API_KEY
        if not self.api_key:
            raise TranslationError(
                "No OpenAI API key provided. Set OPENAI_API_KEY environment variable."
            )

    async def translate(
        self,
        text: str,
        prompt_template: str,
        max_retries: int = 3,
        initial_backoff: float = 1.0,
    ) -> str:
        """
        Translate text using OpenAI's API.

        Args:
            text: The text to translate
            prompt_template: The prompt template to use
            max_retries: Maximum number of retry attempts for rate limit errors
            initial_backoff: Initial backoff time in seconds

        Returns:
            The translated text

        Raises:
            TranslationError: If translation fails after all retry attempts
            RateLimitedError: If rate limits are hit and retries are exhausted
        """
        if not OPENAI_AVAILABLE:
            raise TranslationError(
                "OpenAI package is not installed. Install with 'pip install openai'."
            )

        # Create OpenAI client
        client = AsyncOpenAI(api_key=self.api_key)

        # Fill in the template with the text to translate
        prompt = prompt_template.replace("{{TEXT}}", text)

        # Initialize retry parameters
        retry_count = 0
        backoff_time = initial_backoff

        while True:
            try:
                logger.info(f"Translating text using OpenAI model: {self.model_name}")

                completion = await client.chat.completions.create(
                    model=self.model_name,
                    max_tokens=1024,
                    messages=[{"role": "user", "content": prompt}],
                )

                # Extract the translated text from the response
                if not completion.choices:
                    logger.error("No choices in OpenAI response")
                    raise TranslationError("No translation returned from OpenAI API")

                return completion.choices[0].message.content or ""

            except (OpenAIRateLimitError, OpenAIAPIStatusError) as e:
                # Check if this is a rate limit error (either direct RateLimitError or status code 429)
                is_rate_limit = isinstance(e, OpenAIRateLimitError) or (
                    isinstance(e, OpenAIAPIStatusError) and e.status_code == 429
                )

                if is_rate_limit and retry_count < max_retries:
                    retry_count += 1
                    logger.warning(
                        f"Rate limit error from OpenAI API. Retrying ({retry_count}/{max_retries}) "
                        f"in {backoff_time:.2f} seconds..."
                    )

                    # Exponential backoff with jitter
                    jitter = random.uniform(0.8, 1.2)  # ±20% jitter
                    await asyncio.sleep(backoff_time * jitter)

                    # Increase backoff for next attempt (exponential)
                    backoff_time *= 2
                elif is_rate_limit:
                    # We've exhausted retries for rate limits
                    logger.error(
                        f"OpenAI translation failed after {retry_count} retries due to rate limits: {str(e)}"
                    )
                    raise RateLimitedError(
                        f"OpenAI translation failed due to rate limits: {str(e)}"
                    )
                else:
                    # Not a rate limit error
                    logger.error(f"OpenAI API error: {str(e)}")
                    raise TranslationError(
                        f"OpenAI translation failed with API error: {str(e)}"
                    )

            except Exception as e:
                # Not a rate limit error, don't retry
                logger.error(
                    f"OpenAI translation failed with non-retryable error: {str(e)}"
                )
                raise TranslationError(f"OpenAI translation failed: {str(e)}")


async def translate(
    text: str,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    max_retries: int = 3,
    initial_backoff: float = 1.0,
) -> str:
    """
    Translate text from Japanese to Korean using configured LLM providers.
    Will try each provider in order until one succeeds or all fail.

    Args:
        text: The Japanese text to translate
        api_key: API key for the service (defaults to appropriate config values)
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

    # Backward compatibility for direct model specification
    if model and not api_key:
        # If a model is specified directly but no API key, assume it's an Anthropic model
        # and add it to the front of the models list just for this request
        model_spec = f"anthropic:{model}"
        models_to_try = [model_spec] + config.common.TRANSLATION_MODELS
    else:
        # Use the configured models list
        models_to_try = config.common.TRANSLATION_MODELS

    # Load translation prompt
    try:
        prompt_path = os.path.join(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            ),
            "prompts",
            "translate.prompt",
        )

        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt_template = f.read()

    except Exception as e:
        logger.error(f"Failed to load translation prompt: {str(e)}")
        raise TranslationError(f"Failed to load translation prompt: {str(e)}")

    # Try each model in order
    errors = []

    for model_spec in models_to_try:
        try:
            # Parse provider:model format
            if ":" not in model_spec:
                logger.warning(
                    f"Invalid model specification '{model_spec}'. Must be in 'provider:model' format."
                )
                continue

            provider_name, model_name = model_spec.split(":", 1)

            # Check for API key override
            if api_key and provider_name.lower() == "anthropic":
                # For backward compatibility
                custom_api_key = api_key
            else:
                custom_api_key = None

            # Create provider instance
            provider = LLMProvider.create(provider_name, model_name)
            if not provider:
                logger.warning(
                    f"Provider '{provider_name}' is not available. Skipping."
                )
                continue

            # If api_key was provided and it's compatible with this provider, use it
            if custom_api_key and isinstance(provider, AnthropicProvider):
                provider.api_key = custom_api_key

            # Try to translate with this provider
            try:
                translated_text = await provider.translate(
                    text=text,
                    prompt_template=prompt_template,
                    max_retries=max_retries,
                    initial_backoff=initial_backoff,
                )
                return translated_text

            except RateLimitedError as e:
                # Rate limit errors should cause us to try the next provider
                logger.warning(
                    f"Rate limited with {provider_name}:{model_name}. Trying next provider."
                )
                errors.append(f"{provider_name}:{model_name} - Rate limited: {str(e)}")
                continue

            except TranslationError as e:
                # Other translation errors should also be retried with the next provider
                logger.warning(
                    f"Translation failed with {provider_name}:{model_name}: {str(e)}. Trying next provider."
                )
                errors.append(f"{provider_name}:{model_name} - Error: {str(e)}")
                continue

        except Exception as e:
            # General errors with this provider, try the next one
            logger.warning(
                f"Error with provider {model_spec}: {str(e)}. Trying next provider."
            )
            errors.append(f"{model_spec} - Error: {str(e)}")
            continue

    # If we get here, all providers failed
    error_message = "All translation providers failed: " + "; ".join(errors)
    logger.error(error_message)
    raise TranslationError(error_message)
