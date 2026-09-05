from ._base import ApiModel
from .tweet import Tweet


class AdvancedSearchResponse(ApiModel):
    tweets: list[Tweet] | None = None
    has_next_page: bool | None = None
    next_cursor: str | None = None
