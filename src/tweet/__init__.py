import os
from typing import Literal, Optional

import httpx

from .types import AdvancedSearchResponse, Tweet, UserInfo


class TwitterAPI:
    BASE_URL = "https://api.twitterapi.io"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("TWITTERAPI_IO_API_KEY")
        if not self.api_key:
            raise ValueError(
                "API key must be provided either as argument or via TWITTERAPI_IO_API_KEY environment variable"
            )

        self.session = httpx.AsyncClient(
            base_url=self.BASE_URL, headers={"X-API-Key": self.api_key}, timeout=30.0
        )

    async def get_user_info(self, username: str) -> UserInfo:
        """
        Get user information by username.

        Args:
            username: Twitter username (without @)

        Returns:
            UserInfo object with user details

        Raises:
            httpx.HTTPStatusError: If the API returns an error
        """
        response = await self.session.get(
            "/twitter/user/info", params={"userName": username}
        )

        if response.status_code != 200:
            error_data = response.json()
            raise httpx.HTTPStatusError(
                f"API error {error_data.get('error', response.status_code)}: {error_data.get('message', 'Unknown error')}",
                request=response.request,
                response=response,
            )

        data = response.json()
        return UserInfo(**data.get("data", {}))

    async def advanced_search(
        self,
        query: str,
        query_type: Literal["Latest", "Top"] = "Latest",
        cursor: Optional[str] = None,
    ) -> AdvancedSearchResponse:
        """
        Perform advanced search for tweets.

        Args:
            query: Search query (e.g., "AI" OR "Twitter from:elonmusk")
            query_type: "Latest" for most recent tweets or "Top" for popular tweets
            cursor: Pagination cursor for fetching next page of results

        Returns:
            Response object containing tweets and pagination info

        Raises:
            httpx.HTTPStatusError: If the API returns an error
        """
        params = {"query": query, "queryType": query_type}

        if cursor:
            params["cursor"] = cursor

        response = await self.session.get(
            "/twitter/tweet/advanced_search", params=params
        )

        if response.status_code != 200:
            error_data = response.json()
            raise httpx.HTTPStatusError(
                f"API error {error_data.get('error', response.status_code)}: {error_data.get('message', 'Unknown error')}",
                request=response.request,
                response=response,
            )

        data = response.json()
        return AdvancedSearchResponse(**data)

    async def close(self):
        """Close the HTTP session."""
        await self.session.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
