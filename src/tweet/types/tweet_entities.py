from ._base import ApiModel


class Hashtag(ApiModel):
    indices: list[int] | None = None
    text: str | None = None


class Url(ApiModel):
    display_url: str | None = None
    expanded_url: str | None = None
    indices: list[int] | None = None
    url: str | None = None


class UserMention(ApiModel):
    id_str: str | None = None
    name: str | None = None
    screen_name: str | None = None
    indices: list[int] | None = None


class TweetEntities(ApiModel):
    hashtags: list[Hashtag] | None = None
    urls: list[Url] | None = None
    user_mentions: list[UserMention] | None = None
