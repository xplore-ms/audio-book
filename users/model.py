from datetime import datetime
from typing import Dict
from pydantic import BaseModel, Field


class User(BaseModel):
    id: str
    email: str

    credits: int = 10  # free tier on signup


    last_login: datetime | None = None
