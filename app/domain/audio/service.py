from typing import Dict, Any
from app.domain.audio import repository as audio_repo


def get_audio_job(job_id: str) -> Dict[str, Any]:
    job = audio_repo.find_job_by_id(job_id)
    if not job:
        raise ValueError("Job not found")
    return job
