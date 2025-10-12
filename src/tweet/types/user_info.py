from typing import List, Optional

from pydantic import BaseModel


class UserInfo(BaseModel):
    type: Optional[str] = None
    userName: Optional[str] = None
    url: Optional[str] = None
    id: Optional[str] = None
    name: Optional[str] = None
    isBlueVerified: Optional[bool] = None
    verifiedType: Optional[str] = None
    profilePicture: Optional[str] = None
    coverPicture: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    followers: Optional[int] = None
    following: Optional[int] = None
    canDm: Optional[bool] = None
    createdAt: Optional[str] = None
    favouritesCount: Optional[int] = None
    hasCustomTimelines: Optional[bool] = None
    isTranslator: Optional[bool] = None
    mediaCount: Optional[int] = None
    statusesCount: Optional[int] = None
    withheldInCountries: Optional[List[str]] = None
    possiblySensitive: Optional[bool] = None
    pinnedTweetIds: Optional[List[str]] = None
    isAutomated: Optional[bool] = None
    automatedBy: Optional[str] = None
    unavailable: Optional[bool] = None
    message: Optional[str] = None
    unavailableReason: Optional[str] = None

    class Config:
        extra = "allow"
