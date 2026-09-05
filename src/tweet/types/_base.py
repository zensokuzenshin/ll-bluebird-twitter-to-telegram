from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Unknown fields are kept, so a change on twitterapi.io's side shows up
    in the logs rather than failing validation outright."""

    model_config = ConfigDict(extra="allow")
