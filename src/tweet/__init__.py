import os
from typing import Any, Literal

import httpx

from .types import AdvancedSearchResponse, Tweet, UserInfo

__all__ = ["AdvancedSearchResponse", "Tweet", "TwitterAPI", "UserInfo"]


class TwitterAPI:
    BASE_URL = "https://api.twitterapi.io"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("TWITTERAPI_IO_API_KEY")
        if not self.api_key:
            raise ValueError(
                "API key must be provided either as argument or via TWITTERAPI_IO_API_KEY environment variable"
            )

        self.session = httpx.AsyncClient(
            base_url=self.BASE_URL, headers={"X-API-Key": self.api_key}, timeout=30.0
        )

    async def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        """Raises httpx.HTTPStatusError carrying whatever detail the API gave."""
        response = await self.session.get(path, params=params)

        if response.status_code != 200:
            try:
                error = response.json()
            except ValueError:
                error = {}
            raise httpx.HTTPStatusError(
                f"API error {error.get('error', response.status_code)}: "
                f"{error.get('message', 'Unknown error')}",
                request=response.request,
                response=response,
            )

        return response.json()

    async def get_user_info(self, username: str) -> UserInfo:
        """`username` is the handle without the leading @."""
        data = await self._get("/twitter/user/info", {"userName": username})
        return UserInfo(**data.get("data", {}))

    async def advanced_search(
        self,
        query: str,
        query_type: Literal["Latest", "Top"] = "Latest",
        cursor: str | None = None,
    ) -> AdvancedSearchResponse:
        """Search tweets, e.g. `"AI" OR "Twitter" from:elonmusk`."""
        params = {"query": query, "queryType": query_type}
        if cursor:
            params["cursor"] = cursor

        data = await self._get("/twitter/tweet/advanced_search", params)
        return AdvancedSearchResponse(**data)

    async def close(self):
        await self.session.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
