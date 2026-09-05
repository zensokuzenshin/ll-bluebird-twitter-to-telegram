from ._base import ApiModel


class UserInfo(ApiModel):
    type: str | None = None
    userName: str | None = None
    url: str | None = None
    id: str | None = None
    name: str | None = None
    isBlueVerified: bool | None = None
    verifiedType: str | None = None
    profilePicture: str | None = None
    coverPicture: str | None = None
    description: str | None = None
    location: str | None = None
    followers: int | None = None
    following: int | None = None
    canDm: bool | None = None
    createdAt: str | None = None
    favouritesCount: int | None = None
    hasCustomTimelines: bool | None = None
    isTranslator: bool | None = None
    mediaCount: int | None = None
    statusesCount: int | None = None
    withheldInCountries: list[str] | None = None
    possiblySensitive: bool | None = None
    pinnedTweetIds: list[str] | None = None
    isAutomated: bool | None = None
    automatedBy: str | None = None
    unavailable: bool | None = None
    message: str | None = None
    unavailableReason: str | None = None
