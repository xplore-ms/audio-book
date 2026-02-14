from typing import Any, Dict, Optional
from app.db.mongo import jobs_collection


def find_job(job_id: str) -> Optional[Dict[str, Any]]:
    return jobs_collection.find_one({"job_id": job_id})


def save_job(job_doc: Dict[str, Any]):
    return jobs_collection.insert_one(job_doc)
