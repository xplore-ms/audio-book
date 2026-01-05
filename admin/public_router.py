import io
import wave
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse, JSONResponse
from mongo import jobs_collection, users_collection
from supabase_client import download_to_bytes
from core.dependencies import get_current_user

public_router = APIRouter(prefix="/public", tags=["Public Library"])


@public_router.get("/")
def list_public_audios():
    jobs = jobs_collection.find(
        {"is_admin": True},
        {"_id": 0, "job_id": 1, "required_credits": 1,"title": 1, 
            "file_name": 1,
            "created_at": 1}
    )
    return list(jobs)


@public_router.get("/listen/{job_id}")
def stream_public_audio(job_id: str, token: str = Query(...)):
    user = get_current_user(token)

    job = jobs_collection.find_one({"job_id": job_id, "is_admin": True})
    if not job:
        raise HTTPException(404, "Job not found")

    pages = job.get("pages", {})
    if not pages:
        raise HTTPException(404, "No audio pages")

    def page_sort_key(item):
        return int(item[0].split("_")[-1])

    ordered_pages = sorted(pages.items(), key=page_sort_key)
    user_doc = users_collection.find_one({"_id": user["_id"]})
    user_credits = user_doc.get("credits", 0)
    required = job.get("required_credits", 0)

    if user_credits < required:
        raise HTTPException(
            status_code=403,
            detail=f"Not enough credits. Required: {required}, you have: {user_credits}"
        )

    users_collection.update_one({"_id": user["_id"]}, {"$inc": {"credits": -required}})

    pcm_chunks = []
    params = None
    total_frames = 0

    def extract_storage_path(public_url: str) -> str:
        marker = f"/storage/v1/object/public/reading_app/"
        if marker not in public_url:
            raise RuntimeError("Invalid Supabase public URL format")
        return public_url.split(marker, 1)[1]

    for _, page in ordered_pages:
        print(page["audio_url"], "Supabase Urll")
        wav_bytes = download_to_bytes(
            extract_storage_path(page["audio_url"])
        )

        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            if params is None:
                params = w.getparams()

            frames = w.readframes(w.getnframes())
            pcm_chunks.append(frames)
            total_frames += w.getnframes()
            
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

@public_router.get("/download/{job_id}")
def download_public_audio(job_id: str, token: str = Query(...)):
    user = get_current_user(token)

    job = jobs_collection.find_one({
        "job_id": job_id,
        "is_admin": True
    })
    if not job:
        raise HTTPException(404, "Job not found")

    pages = job.get("pages", {})
    if not pages:
        raise HTTPException(404, "No audio pages")

    def page_sort_key(item):
        return int(item[0].split("_")[-1])

    ordered_pages = sorted(pages.items(), key=page_sort_key)

    # ---- Credit check ----
    user_doc = users_collection.find_one({"_id": user["_id"]})
    user_credits = user_doc.get("credits", 0)
    required = job.get("required_credits", 0)

    if user_credits < required:
        raise HTTPException(
            status_code=403,
            detail=f"Not enough credits. Required: {required}, you have: {user_credits}"
        )

    users_collection.update_one(
        {"_id": user["_id"]},
        {"$inc": {"credits": -required}}
    )

    # ---- Build final WAV ----
    pcm_chunks = []
    params = None

    def extract_storage_path(public_url: str) -> str:
        marker = "/storage/v1/object/public/reading_app/"
        if marker not in public_url:
            raise RuntimeError("Invalid Supabase public URL format")
        return public_url.split(marker, 1)[1]

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

    filename = f"{job.get('title', job_id)}.wav"

    return StreamingResponse(
        wav_file(),
        media_type="audio/wav",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store"
        }
    )


@public_router.get("/sync/{job_id}")
def get_sync(job_id: str):
    job = jobs_collection.find_one({"job_id": job_id})
    if not job or "pages" not in job:
        raise HTTPException(status_code=404, detail="Sync info not available")

    return JSONResponse({"pages": job["pages"]})

