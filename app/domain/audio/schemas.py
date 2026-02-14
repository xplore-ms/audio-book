from pydantic import BaseModel
from typing import Optional


class AudioJob(BaseModel):
    job_id: str
    user_id: str
    num_pages: Optional[int] = None
