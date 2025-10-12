import datetime
import logging
from typing import List, Optional

from pydantic import BaseModel, computed_field

from .tweet_entities import TweetEntities
from .user_info import UserInfo

logger = logging.getLogger(__name__)


class Tweet(BaseModel):
    type: Optional[str] = None
    id: Optional[str] = None
    url: Optional[str] = None
    text: Optional[str] = None
    source: Optional[str] = None
    retweetCount: Optional[int] = None
    replyCount: Optional[int] = None
    likeCount: Optional[int] = None
    quoteCount: Optional[int] = None
    viewCount: Optional[int] = None
    createdAt: Optional[str] = None
    lang: Optional[str] = None
    bookmarkCount: Optional[int] = None
    isReply: Optional[bool] = None
    inReplyToId: Optional[str] = None
    conversationId: Optional[str] = None
    displayTextRange: Optional[List[int]] = None
    inReplyToUserId: Optional[str] = None
    inReplyToUsername: Optional[str] = None
    author: Optional[UserInfo] = None
    entities: Optional[TweetEntities] = None
    quoted_tweet: Optional["Tweet"] = None
    retweeted_tweet: Optional["Tweet"] = None
    isLimitedReply: Optional[bool] = None

    @computed_field
    @property
    def created_at_dt(self) -> Optional[datetime.datetime]:
        if self.createdAt:
            return datetime.datetime.strptime(self.createdAt, "%a %b %d %H:%M:%S %z %Y")
        return None

    class Config:
        extra = "allow"
