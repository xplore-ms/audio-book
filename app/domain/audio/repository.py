from typing import Any, Dict, Optional
from app.db.mongo import jobs_collection


def find_job_by_id(job_id: str) -> Optional[Dict[str, Any]]:
    return jobs_collection.find_one({"job_id": job_id})


def update_job(filter_q: Dict[str, Any], update_doc: Dict[str, Any]):
    return jobs_collection.update_one(filter_q, update_doc)
