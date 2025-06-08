import os
from typing import List, Dict

from .types import Character

_characters: List[str] = [
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
]


class _Characters:
    _character_config: Dict[str, Character] = {}
    _twitter_handle_map: Dict[str, Character] = {}

    def __setattr__(self, key: str, value: Character):
        self._character_config[key.lower()] = value
        self._twitter_handle_map[value.twitter_handle.lower()] = value

    def __getattr__(self, key: str) -> Character:
        return self._character_config[key.lower()]

    def __getitem__(self, item: str) -> Character:
        item = item.lower()
        if item in self._twitter_handle_map.keys():
            return self._twitter_handle_map[item]
        else:
            return self._character_config[item]


characters = _Characters()

for character in _characters:
    twitter_handle = os.environ.get(
        f"Character_{character}_Twitter_Handle".upper(), None
    )
    if twitter_handle is None:
        raise ValueError(f"Twitter Handle of {character} is not defined")
    telegram_bot_token = os.environ.get(
        f"Character_{character}_Telegram_Bot_Token".upper(), None
    )
    if telegram_bot_token is None:
        raise ValueError(f"Telegram Bot Token of {character} is not defined")

    setattr(
        characters,
        character,
        Character(
            name=character,
            twitter_handle=twitter_handle,
            telegram_bot_token=telegram_bot_token,
        ),
    )

__all__ = ["characters"]
