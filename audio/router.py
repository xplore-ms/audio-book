from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from supabase_client import download_to_bytes
from mongo import jobs_collection
from core.dependencies import get_current_user
import os

from dotenv import load_dotenv
load_dotenv()
router = APIRouter(prefix="/audio", tags=["Audio"])

SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "reading_app")

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

@router.get("/api/audio/stream")
def stream_audio(token: str):
    job = jobs_collection.find_one({"access_token": token})
    if not job:
        raise HTTPException(status_code=403, detail="Invalid or expired token")

    final_parts = job.get("final_parts", [])
    if not final_parts:
        raise HTTPException(status_code=404, detail="Audio not found")

    def extract_storage_path(public_url: str) -> str:
        """
        Converts:
        https://xxx.supabase.co/storage/v1/object/public/reading_app/pdfs/abc.wav

        To:
        pdfs/abc.wav
        """
        marker = f"/storage/v1/object/public/{SUPABASE_BUCKET}/"
        if marker not in public_url:
            raise RuntimeError("Invalid Supabase public URL format")
        return public_url.split(marker, 1)[1]

    def audio_generator():
        for idx, public_url in enumerate(final_parts):
            storage_path = extract_storage_path(public_url)

            audio_bytes = download_to_bytes(storage_path)

            # Strip WAV header for all except first
            if idx > 0:
                audio_bytes = audio_bytes[44:]

            yield audio_bytes

    return StreamingResponse(
        audio_generator(),
        media_type="audio/wav",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": "inline; filename=audiobook.wav"
        }
    )

@router.get("/api/audio/download")
def download_audio(token: str):
    job = jobs_collection.find_one({"access_token": token})
    if not job:
        raise HTTPException(status_code=403, detail="Invalid or expired token")

    final_parts = job.get("final_parts", [])
    if not final_parts:
        raise HTTPException(status_code=404, detail="Audio not found")

    def extract_storage_path(public_url: str) -> str:
        marker = f"/storage/v1/object/public/{SUPABASE_BUCKET}/"
        if marker not in public_url:
            raise RuntimeError("Invalid Supabase public URL format")
        return public_url.split(marker, 1)[1]

    output = io.BytesIO()

    for idx, public_url in enumerate(final_parts):
        storage_path = extract_storage_path(public_url)
        audio_bytes = download_to_bytes(storage_path)

        # Remove WAV header for all except first
        if idx > 0:
            audio_bytes = audio_bytes[44:]

        output.write(audio_bytes)

    output.seek(0)

    return StreamingResponse(
        output,
        media_type="audio/wav",
        headers={
            "Content-Disposition": "attachment; filename=audiobook.wav",
            "Content-Length": str(output.getbuffer().nbytes),
            "Cache-Control": "no-store"
        }
    )
