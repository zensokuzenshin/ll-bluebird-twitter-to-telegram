from typing import Optional

from async_property import async_cached_property
from pydantic import computed_field

from tweet.types import Tweet

from .. import translate


class TranslatedTweet(Tweet):
    translation_provider: Optional[str] = None

    @computed_field(return_type=str)
    @async_cached_property
    async def text_translated(self) -> str:
        translated, model = await translate(self.text)
        if model is None:
            raise RuntimeError("Translation failed")

        self.translation_provider = model
        return translated
