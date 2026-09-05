import os
from collections.abc import Iterable, Iterator

from .types import Character

_CHARACTER_NAMES = (
    "Polka",
    "Mai",
    "Akira",
    "Hanabi",
    "Miracle",
    "Noriko",
    "Yukuri",
    "Aurora",
    "Midori",
    "Shion",
)


class _Characters:
    """Lookup by character name or Twitter handle, both case-insensitive."""

    def __init__(self, characters: Iterable[Character]) -> None:
        characters = tuple(characters)
        self._by_name = {c.name.lower(): c for c in characters}
        self._by_handle = {c.twitter_handle.lower(): c for c in characters}

    def __getattr__(self, name: str) -> Character:
        # Bail out before touching self._by_name, or a lookup during __init__
        # would recurse forever.
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self._by_name[name.lower()]
        except KeyError:
            raise AttributeError(name) from None

    def __getitem__(self, key: str) -> Character:
        key = key.lower()
        if key in self._by_handle:
            return self._by_handle[key]
        return self._by_name[key]

    def __iter__(self) -> Iterator[Character]:
        return iter(self._by_name.values())

    def __len__(self) -> int:
        return len(self._by_name)

    @property
    def twitter_handles(self) -> frozenset[str]:
        """Lowercased: the search API echoes handles back with varying casing."""
        return frozenset(self._by_handle)


def _load(name: str) -> Character:
    def required(suffix: str) -> str:
        key = f"Character_{name}_{suffix}".upper()
        value = os.environ.get(key)
        if not value:
            raise ValueError(f"{key} is not defined")
        return value

    return Character(
        name=name,
        twitter_handle=required("Twitter_Handle"),
        telegram_bot_token=required("Telegram_Bot_Token"),
    )


characters = _Characters(_load(name) for name in _CHARACTER_NAMES)

__all__ = ["characters"]
