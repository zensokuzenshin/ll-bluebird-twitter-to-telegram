from typing import List, Optional

from pydantic import BaseModel

from .tweet import Tweet


class AdvancedSearchResponse(BaseModel):
    tweets: Optional[List[Tweet]] = None
    has_next_page: Optional[bool] = None
    next_cursor: Optional[str] = None

    class Config:
        extra = "allow"
