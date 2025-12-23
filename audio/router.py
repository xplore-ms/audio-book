from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse, JSONResponse
from supabase_client import download_to_bytes
from mongo import jobs_collection
from core.dependencies import get_current_user
import io
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


@router.get("/pages/{job_id}")
def get_pages(job_id: str, user=Depends(get_current_user)):
    """
    Fetch per-page info (audio URL, sync URL, duration) for a job
    """
    job = jobs_collection.find_one({"job_id": job_id, "user_id": user["_id"]})
    if not job or "pages" not in job:
        raise HTTPException(status_code=404, detail="Pages info not found")

    return {"pages": job["pages"]}

@router.get("/stream/{job_id}")
def stream_audio(job_id: str, token: str = Query(...)):
    user = get_current_user(token)

    job = jobs_collection.find_one(
        {"job_id": job_id, "user_id": user["_id"]}
    )
    if not job or "final_parts" not in job:
        raise HTTPException(status_code=404, detail="Audio not available")

    def iter_audio():
        first = True
        for part_url in job["final_parts"]:
            audio_bytes = download_to_bytes(part_url)
            if not first:
                audio_bytes = audio_bytes[44:]  # strip WAV header
            first = False
            yield audio_bytes

    return StreamingResponse(
        iter_audio(),
        media_type="audio/wav",
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-store"
        }
    )

@router.get("/download/{job_id}")
def download_audio(job_id: str, token: str = Query(...)):
    user = get_current_user(token)

    job = jobs_collection.find_one(
        {"job_id": job_id, "user_id": user["_id"]}
    )
    if not job or "final_parts" not in job:
        raise HTTPException(status_code=404, detail="Audio not available")

    def iter_audio():
        first = True
        for part_url in job["final_parts"]:
            audio_bytes = download_to_bytes(part_url)
            if not first:
                audio_bytes = audio_bytes[44:]
            first = False
            yield audio_bytes

    filename = f"{job.get('folder_name', job_id)}.wav"

    return StreamingResponse(
        iter_audio(),
        media_type="audio/wav",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )



@router.get("/sync/{job_id}")
def get_sync(job_id: str, user=Depends(get_current_user)):
    """
    Return per-page sync info for the frontend to build dynamic global sync.
    """
    job = jobs_collection.find_one({"job_id": job_id, "user_id": user["_id"]})
    if not job or "pages" not in job:
        raise HTTPException(status_code=404, detail="Sync info not available")

    return JSONResponse({"pages": job["pages"]})


@router.get("/download/{job_id}")
def download_audio(job_id: str, user=Depends(get_current_user)):
    """
    Download the full audiobook (merged on-the-fly from final_parts) as a single WAV file.
    """
    job = jobs_collection.find_one({"job_id": job_id, "user_id": user["_id"]})
    if not job or "final_parts" not in job:
        raise HTTPException(status_code=404, detail="Audio not available")

    def iter_audio():
        first_chunk = True
        for part_url in job["final_parts"]:
            audio_bytes = download_to_bytes(part_url)
            
            if not first_chunk:
                # Remove WAV header for all chunks after the first
                audio_bytes = audio_bytes[44:]
            else:
                first_chunk = False

            yield audio_bytes

    filename = f"{job.get('folder_name', job_id)}.wav"

    return StreamingResponse(
        iter_audio(),
        media_type="audio/wav",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.get("/stream/page/{job_id}/{page}")
def stream_page_audio(job_id: str, page: str, user=Depends(get_current_user)):
    """
    Stream a single page’s audio.
    """
    job = jobs_collection.find_one({"job_id": job_id, "user_id": user["_id"]})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    audio_url = job.get("pages", {}).get(page, {}).get("audio_url")
    if not audio_url:
        raise HTTPException(status_code=404, detail="Audio for this page not found")

    audio_bytes = download_to_bytes(audio_url)
    return StreamingResponse(io.BytesIO(audio_bytes), media_type="audio/wav")


