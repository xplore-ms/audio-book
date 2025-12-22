from datetime import datetime
from typing import Dict
from pydantic import BaseModel, Field


class User(BaseModel):
    id: str
    email: str

    credits: int = 10  # free tier on signup

    tasks: Dict[str, bool] = Field(default_factory=lambda: {
        "daily_login": False,
        "twitter_follow": False,
    })

    last_login: datetime | None = None
