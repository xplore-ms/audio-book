from pydantic import BaseModel


class JobSchema(BaseModel):
    job_id: str
    user_id: str
