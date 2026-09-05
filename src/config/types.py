from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Character:
    name: str
    twitter_handle: str
    telegram_bot_token: str
