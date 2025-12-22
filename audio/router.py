from fastapi import APIRouter, HTTPException, Depends
from mongo import jobs_collection
from core.dependencies import get_current_user

router = APIRouter(prefix="/audio", tags=["Audio"])

@router.get("/my")
def my_audios(user=Depends(get_current_user)):
    """
    Fetch all completed audios for the authenticated user
    """
    jobs = jobs_collection.find(
        {"user_id": user["_id"], "final_parts": {"$exists": True}},
        {"_id": 0, "job_id": 1, "final_parts": 1, "final_size_mb": 1}
    )
    return list(jobs)


@router.get("/sync/{job_id}")
def get_sync(job_id: str, user=Depends(get_current_user)):
    """
    Fetch per-page sync JSON for a given job.
    """
    job = jobs_collection.find_one({"job_id": job_id, "user_id": user["_id"]})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.get("sync", {})


@router.get("/sync/global/{job_id}")
def get_global_sync(job_id: str, user=Depends(get_current_user)):
    """
    Fetch global sync JSON for a given job.
    """
    job = jobs_collection.find_one({"job_id": job_id, "user_id": user["_id"]})
    if not job or "global_sync_url" not in job:
        raise HTTPException(status_code=404, detail="Global sync not available")
    return {"global_sync_url": job["global_sync_url"]}
