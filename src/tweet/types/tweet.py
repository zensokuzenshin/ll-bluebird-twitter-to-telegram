import datetime
import logging

from ._base import ApiModel
from .tweet_entities import TweetEntities
from .user_info import UserInfo

logger = logging.getLogger(__name__)

# e.g. "Sun Jun 08 12:34:56 +0000 2025"
_CREATED_AT_FORMAT = "%a %b %d %H:%M:%S %z %Y"


class Tweet(ApiModel):
    type: str | None = None
    id: str | None = None
    url: str | None = None
    text: str | None = None
    source: str | None = None
    retweetCount: int | None = None
    replyCount: int | None = None
    likeCount: int | None = None
    quoteCount: int | None = None
    viewCount: int | None = None
    createdAt: str | None = None
    lang: str | None = None
    bookmarkCount: int | None = None
    isReply: bool | None = None
    inReplyToId: str | None = None
    conversationId: str | None = None
    displayTextRange: list[int] | None = None
    inReplyToUserId: str | None = None
    inReplyToUsername: str | None = None
    author: UserInfo | None = None
    entities: TweetEntities | None = None
    quoted_tweet: Tweet | None = None
    retweeted_tweet: Tweet | None = None
    isLimitedReply: bool | None = None

    @property
    def created_at_dt(self) -> datetime.datetime | None:
        """Not a `computed_field`: including it in `model_dump()` would make
        the dump impossible to feed back into the model."""
        if not self.createdAt:
            return None
        try:
            # _CREATED_AT_FORMAT does carry %z; ruff cannot see through the constant
            return datetime.datetime.strptime(self.createdAt, _CREATED_AT_FORMAT)  # noqa: DTZ007
        except ValueError:
            logger.warning(
                "Tweet %s has an unparseable createdAt: %r", self.id, self.createdAt
            )
            return None
