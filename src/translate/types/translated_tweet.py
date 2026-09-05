from pydantic import PrivateAttr

from tweet.types import Tweet

from .. import translate


class TranslatedTweet(Tweet):
    """A tweet plus its Korean translation, produced once on first request."""

    translation_provider: str | None = None

    _translated: str | None = PrivateAttr(default=None)

    async def text_translated(self) -> str:
        if self._translated is None:
            translated, provider = await translate(self.text or "")
            if provider is None:
                raise RuntimeError("Translation failed")

            self.translation_provider = provider
            self._translated = translated

        return self._translated
