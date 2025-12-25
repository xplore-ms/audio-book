from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from mongo import jobs_collection, users_collection
from supabase_client import download_to_bytes
from core.dependencies import get_current_user

public_router = APIRouter(prefix="/public", tags=["Public Library"])


@public_router.get("/")
def list_public_audios():
    jobs = jobs_collection.find(
        {"is_admin": True, "final_parts": {"$exists": True}},
        {"_id": 0, "job_id": 1, "final_parts": 1, "final_size_mb": 1, "required_credits": 1}
    )
    return list(jobs)


@public_router.get("/listen/{job_id}")
def stream_public_audio(job_id: str, user=Depends(get_current_user)):
    job = jobs_collection.find_one({"job_id": job_id, "is_admin": True})
    if not job or "final_parts" not in job:
        raise HTTPException(status_code=404, detail="Audio not found")

    user_doc = users_collection.find_one({"_id": user["_id"]})
    user_credits = user_doc.get("credits", 0)
    required = job.get("required_credits", 1)

    if user_credits < required:
        raise HTTPException(
            status_code=403,
            detail=f"Not enough credits. Required: {required}, you have: {user_credits}"
        )

    users_collection.update_one({"_id": user["_id"]}, {"$inc": {"credits": -required}})

    final_parts = job["final_parts"]

    def extract_storage_path(public_url: str) -> str:
        marker = f"/storage/v1/object/public/admin_library/"
        if marker not in public_url:
            raise RuntimeError("Invalid Supabase public URL format")
        return public_url.split(marker, 1)[1]

    def audio_generator():
        for idx, public_url in enumerate(final_parts):
            storage_path = extract_storage_path(public_url)
            audio_bytes = download_to_bytes(storage_path)
            if idx > 0:
                audio_bytes = audio_bytes[44:]  # strip WAV header
            yield audio_bytes

    return StreamingResponse(
        audio_generator(),
        media_type="audio/wav",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": "inline; filename=audiobook.wav"
        }
    )


@public_router.get("/sync/{job_id}")
def get_sync(job_id: str):
    job = jobs_collection.find_one({"job_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.get("sync", {})


@public_router.get("/sync/global/{job_id}")
def get_global_sync(job_id: str):
    job = jobs_collection.find_one({"job_id": job_id})
    if not job or "global_sync_url" not in job:
        raise HTTPException(status_code=404, detail="Global sync not available")
    return {"global_sync_url": job["global_sync_url"]}
