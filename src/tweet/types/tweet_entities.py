from typing import List, Optional

from pydantic import BaseModel


class Hashtag(BaseModel):
    indices: Optional[List[int]] = None
    text: Optional[str] = None

    class Config:
        extra = "allow"


class Url(BaseModel):
    display_url: Optional[str] = None
    expanded_url: Optional[str] = None
    indices: Optional[List[int]] = None
    url: Optional[str] = None

    class Config:
        extra = "allow"


class UserMention(BaseModel):
    id_str: Optional[str] = None
    name: Optional[str] = None
    screen_name: Optional[str] = None
    indices: Optional[List[int]] = None

    class Config:
        extra = "allow"


class TweetEntities(BaseModel):
    hashtags: Optional[List[Hashtag]] = None
    urls: Optional[List[Url]] = None
    user_mentions: Optional[List[UserMention]] = None

    class Config:
        extra = "allow"
