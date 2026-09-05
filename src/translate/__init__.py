"""Japanese to Korean tweet translation, via prompts/translate.prompt.

Several LLM providers are tried in turn so a rate limit or outage at one does
not stall the forwarder.
"""

import asyncio
import logging
import random
import time
from abc import ABC, abstractmethod
from functools import cache
from pathlib import Path

from anthropic import APIStatusError as AnthropicAPIStatusError
from anthropic import AsyncAnthropic
from anthropic import RateLimitError as AnthropicRateLimitError
from anthropic.types import MessageParam
from openai import APIStatusError as OpenAIAPIStatusError
from openai import AsyncOpenAI
from openai import RateLimitError as OpenAIRateLimitError

import config
import telemetry

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "translate.prompt"
# Only a ceiling, never a charge, and the current models spend a chunk of it
# reasoning before they emit anything. Keep it well clear of a long tweet.
_MAX_TOKENS = 4096


class TranslationError(Exception):
    """Exception raised for errors during translation."""


class RateLimitedError(TranslationError):
    """Exception raised when API rate limits are hit."""


@cache
def _prompt_template() -> str:
    try:
        return _PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as e:
        raise TranslationError(f"Failed to load translation prompt: {e}") from e


def _is_rate_limited(error: Exception) -> bool:
    """Both SDKs raise a dedicated error, but only for a clean 429."""
    if isinstance(error, AnthropicRateLimitError | OpenAIRateLimitError):
        return True
    return (
        isinstance(error, AnthropicAPIStatusError | OpenAIAPIStatusError)
        and error.status_code == 429
    )


class LLMProvider(ABC):
    """A single chat model, with retry handling shared across providers."""

    name: str

    def __init__(self, model_name: str):
        self.model_name = model_name

    def __str__(self) -> str:
        return f"{self.name}:{self.model_name}"

    @abstractmethod
    async def complete(self, prompt: str) -> str:
        """Send `prompt` to the model and return its reply."""

    def _count(self, outcome: str) -> None:
        telemetry.translations.add(
            1, {"provider": self.name, "model": self.model_name, "outcome": outcome}
        )

    async def translate(
        self,
        text: str,
        max_retries: int = 3,
        initial_backoff: float = 1.0,
    ) -> str:
        """Raises RateLimitedError once retries run out, TranslationError otherwise."""
        prompt = _prompt_template().replace("{{TEXT}}", text)
        backoff = initial_backoff
        attempt = 0
        started = time.monotonic()

        while True:
            try:
                logger.info("Translating text using %s", self)
                with telemetry.tracer.start_as_current_span(
                    "translate",
                    attributes={
                        "gen_ai.system": self.name,
                        "gen_ai.request.model": self.model_name,
                    },
                ):
                    translated = await self.complete(prompt)
            except TranslationError:
                self._count("error")
                raise
            except Exception as e:
                if not _is_rate_limited(e):
                    self._count("error")
                    logger.error("%s failed with a non-retryable error: %s", self, e)
                    raise TranslationError(f"{self} translation failed: {e}") from e

                if attempt >= max_retries:
                    self._count("rate_limited")
                    logger.error(
                        "%s still rate limited after %d retries: %s", self, attempt, e
                    )
                    raise RateLimitedError(
                        f"{self} translation failed due to rate limits: {e}"
                    ) from e

                attempt += 1
                delay = backoff * random.uniform(0.8, 1.2)  # ±20% jitter
                logger.warning(
                    "Rate limited by %s. Retrying (%d/%d) in %.2f seconds...",
                    self,
                    attempt,
                    max_retries,
                    delay,
                )
                await asyncio.sleep(delay)
                backoff *= 2
            else:
                self._count("success")
                telemetry.translation_duration.record(
                    time.monotonic() - started,
                    {"provider": self.name, "model": self.model_name},
                )
                return translated


@cache
def _anthropic_client() -> AsyncAnthropic:
    if not config.common.ANTHROPIC_API_KEY:
        raise TranslationError(
            "No Anthropic API key provided. Set ANTHROPIC_API_KEY environment variable."
        )
    return AsyncAnthropic(api_key=config.common.ANTHROPIC_API_KEY)


@cache
def _openai_client() -> AsyncOpenAI:
    if not config.common.OPENAI_API_KEY:
        raise TranslationError(
            "No OpenAI API key provided. Set OPENAI_API_KEY environment variable."
        )
    return AsyncOpenAI(api_key=config.common.OPENAI_API_KEY)


class AnthropicProvider(LLMProvider):
    """Anthropic Claude LLM provider."""

    name = "anthropic"

    async def complete(self, prompt: str) -> str:
        message = await _anthropic_client().messages.create(
            model=self.model_name,
            max_tokens=_MAX_TOKENS,
            messages=[MessageParam(role="user", content=prompt)],
        )
        # A truncated translation still looks like a valid one, so refuse it
        # here and let the caller fall through to the next provider.
        if message.stop_reason == "max_tokens":
            raise TranslationError("Anthropic hit max_tokens mid-translation")
        for block in message.content:
            if block.type == "text":
                return block.text
        raise TranslationError("No text content in Anthropic response")


class OpenAIProvider(LLMProvider):
    """OpenAI GPT LLM provider."""

    name = "openai"

    async def complete(self, prompt: str) -> str:
        completion = await _openai_client().chat.completions.create(
            model=self.model_name,
            max_completion_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        if not completion.choices:
            raise TranslationError("No choices in OpenAI response")

        choice = completion.choices[0]
        # Reasoning models can spend the whole budget thinking and come back
        # with finish_reason=length and empty content; that is not a translation.
        if choice.finish_reason == "length":
            raise TranslationError("OpenAI hit the token limit mid-translation")
        if not (choice.message.content or "").strip():
            raise TranslationError("OpenAI returned an empty translation")
        return choice.message.content


_PROVIDERS: dict[str, type[LLMProvider]] = {
    AnthropicProvider.name: AnthropicProvider,
    OpenAIProvider.name: OpenAIProvider,
}


async def translate(
    text: str,
    max_retries: int = 3,
    initial_backoff: float = 1.0,
) -> tuple[str, str | None]:
    """Translate Japanese to Korean, trying each configured model in turn.

    Returns the translation and the "provider:model" behind it; the provider
    is None only when there was nothing to translate. Raises TranslationError
    if every configured provider failed.
    """
    if not text or not text.strip():
        return "", None

    errors = []

    for model_spec in config.common.TRANSLATION_MODELS:
        provider_name, _, model_name = model_spec.partition(":")
        provider_class = _PROVIDERS.get(provider_name.lower())
        if not model_name or provider_class is None:
            logger.warning(
                "Skipping %r: expected a 'provider:model' pair with provider in %s",
                model_spec,
                sorted(_PROVIDERS),
            )
            continue

        provider = provider_class(model_name)
        try:
            return await provider.translate(text, max_retries, initial_backoff), str(
                provider
            )
        except TranslationError as e:
            logger.warning("%s failed: %s. Trying next provider.", provider, e)
            errors.append(f"{provider} - {e}")

    raise TranslationError("All translation providers failed: " + "; ".join(errors))
