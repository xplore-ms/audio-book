from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse, JSONResponse
from supabase_client import download_to_bytes, extract_storage_path
from credits.service import  (
    require_credits,
    deduct_credits,
    DOWNLOAD_COST
)
from mongo import jobs_collection
from core.dependencies import get_current_user
import io
import os
import wave
from dotenv import load_dotenv

load_dotenv()
router = APIRouter(prefix="/audio", tags=["Audio"])
WAV_HEADER_SIZE = 44

SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "reading_app")


@router.get("/my")
def my_audios(user=Depends(get_current_user)):
    """
    Fetch all completed audios for the authenticated user
    """
    jobs = jobs_collection.find(
        {"user_id": str(user["_id"])},
        {
            "_id": 0, 
            "job_id": 1, 
            "title": 1, 
            "file_name": 1,
            "created_at": 1
        }
    )
    return list(jobs)


@router.get("/pages/{job_id}")
def get_pages(job_id: str, user=Depends(get_current_user)):
    """
    Fetch per-page info (audio URL, sync URL, duration) for a job
    """
    job = jobs_collection.find_one({"job_id": job_id, "user_id": str(user["_id"])})
    if not job or "pages" not in job:
        raise HTTPException(status_code=404, detail="Pages info not found")

    return {"pages": job["pages"]}

@router.get("/stream/{job_id}")
def stream_wav(job_id: str, token: str = Query(...)):
    user = get_current_user(token)

    job = jobs_collection.find_one({
        "job_id": job_id,
        "user_id": str(user["_id"])
    })
    if not job:
        raise HTTPException(404, "Job not found")

    pages = job.get("pages", {})
    if not pages:
        raise HTTPException(404, "No audio pages")

    def page_sort_key(item):
        return int(item[0].split("_")[-1])

    ordered_pages = sorted(pages.items(), key=page_sort_key)

    # ---- First pass: read params + total size ----
    pcm_chunks = []
    params = None
    total_frames = 0

    for _, page in ordered_pages:
        wav_bytes = download_to_bytes(
            extract_storage_path(page["audio_url"])
        )

        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            if params is None:
                params = w.getparams()

            frames = w.readframes(w.getnframes())
            pcm_chunks.append(frames)
            total_frames += w.getnframes()

    # ---- Build ONE correct WAV stream ----
    def wav_stream():
        out = io.BytesIO()
        with wave.open(out, "wb") as writer:
            writer.setparams(params)
            for chunk in pcm_chunks:
                writer.writeframes(chunk)

        out.seek(0)
        yield from iter(lambda: out.read(8192), b"")

    return StreamingResponse(
        wav_stream(),
        media_type="audio/wav",
        headers={"Cache-Control": "no-store"}
    )

@router.get("/download/{job_id}")
def download_audio(job_id: str, token: str = Query(...)):
    user = get_current_user(token)

    job = jobs_collection.find_one(
        {"job_id": job_id, "user_id": str(user["_id"])}
    )
    if not job or "pages" not in job:
        raise HTTPException(status_code=404, detail="Audio not available")

    pages = job["pages"]

    require_credits(user, DOWNLOAD_COST)
    deduct_credits(user["_id"], DOWNLOAD_COST)

    def page_sort_key(item):
        return int(item[0].split("_")[-1])

    ordered_pages = sorted(pages.items(), key=page_sort_key)

    pcm_chunks = []
    params = None

    for _, page in ordered_pages:
        wav_bytes = download_to_bytes(
            extract_storage_path(page["audio_url"])
        )

        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            if params is None:
                params = w.getparams()
            pcm_chunks.append(w.readframes(w.getnframes()))

    def wav_file():
        out = io.BytesIO()
        with wave.open(out, "wb") as writer:
            writer.setparams(params)
            for chunk in pcm_chunks:
                writer.writeframes(chunk)
        out.seek(0)
        yield from iter(lambda: out.read(8192), b"")

    filename = f"{job.get('folder_name', job_id)}.wav"

    return StreamingResponse(
        wav_file(),
        media_type="audio/wav",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store"
        }
    )



@router.get("/sync/{job_id}")
def get_sync(job_id: str, user=Depends(get_current_user)):
    """
    Return per-page sync info for the frontend to build dynamic global sync.
    """
    job = jobs_collection.find_one({"job_id": job_id,
                                     "user_id": str(user["_id"])
                                    })
    if not job or "pages" not in job:
        raise HTTPException(status_code=404, detail="Sync info not available")

    return JSONResponse({"pages": job["pages"]})



@router.get("/stream/page/{job_id}/{page}")
def stream_page_audio(job_id: str, page: str, user=Depends(get_current_user)):
    """
    Stream a single page’s audio.
    """
    job = jobs_collection.find_one({"job_id": job_id, "user_id": str(user["_id"])})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    audio_url = job.get("pages", {}).get(page, {}).get("audio_url")
    if not audio_url:
        raise HTTPException(status_code=404, detail="Audio for this page not found")

    audio_bytes = download_to_bytes(audio_url)
    return StreamingResponse(io.BytesIO(audio_bytes), media_type="audio/wav")


