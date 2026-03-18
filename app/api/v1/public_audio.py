import io
import wave
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from app.db.mongo import (
    jobs_collection_async as jobs_collection,
    users_collection_async as users_collection,
)
from app.integrations.supabase.client import (
    build_playlist_response,
    download_to_bytes,
    create_signed_url,
)
from app.core.dependencies import get_current_user

public_router = APIRouter(prefix="/public", tags=["Public Library"])


@public_router.get("/")
async def list_public_audios():
    cursor = jobs_collection.find(
        {"is_admin": True},
        {
            "_id": 0,
            "job_id": 1,
            "required_credits": 1,
            "title": 1,
            "file_name": 1,
            "author": 1,
            "thumbnail_path": 1,
            "created_at": 1,
        },
    )

    jobs = []
    async for job in cursor:
        if job.get("thumbnail_path"):
            try:
                # Generate signed URL valid for 24 hours for discovery
                job["thumbnail_url"] = create_signed_url(
                    job["thumbnail_path"], expires_in=86400
                )
            except Exception as e:
                print(f"Failed to sign thumbnail: {e}")
                job["thumbnail_url"] = None
        jobs.append(job)

    return jobs


@public_router.get("/listen/{job_id}")
async def listen_public_audio(job_id: str, user=Depends(get_current_user)):
    job = await jobs_collection.find_one({"job_id": job_id, "is_admin": True})

    if not job or "pages" not in job:
        raise HTTPException(404, "Audio not found")

    # ---- credit check ----
    user_doc = await users_collection.find_one({"_id": user["_id"]})
    user_credits = user_doc.get("credits", 0)
    required = job.get("required_credits", 0)

    if not job.get("credits_charged"):
        if user_credits < required:
            raise HTTPException(
                status_code=403,
                detail=f"Not enough credits. Required: {required}, you have: {user_credits}",
            )
        await users_collection.update_one(
            {"_id": user["_id"]}, {"$inc": {"credits": -required}}
        )
        await jobs_collection.update_one(
            {"_id": job["_id"]}, {"$set": {"credits_charged": True}}
        )

    return build_playlist_response(job)


@public_router.get("/download/{job_id}")
async def download_public_audio(job_id: str, user=Depends(get_current_user)):
    job = await jobs_collection.find_one({"job_id": job_id, "is_admin": True})
    if not job:
        raise HTTPException(404, "Job not found")

    pages = job.get("pages", {})
    if not pages:
        raise HTTPException(404, "No audio pages")

    def page_sort_key(item):
        return int(item[0].split("_")[-1])

    ordered_pages = sorted(pages.items(), key=page_sort_key)

    # ---- Credit check ----
    user_doc = await users_collection.find_one({"_id": user["_id"]})
    user_credits = user_doc.get("credits", 0)
    required = job.get("required_credits", 0)

    if user_credits < required:
        raise HTTPException(
            status_code=403,
            detail=f"Not enough credits. Required: {required}, you have: {user_credits}",
        )

    await users_collection.update_one(
        {"_id": user["_id"]}, {"$inc": {"credits": -required}}
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
        wav_bytes = download_to_bytes(extract_storage_path(page["audio_url"]))

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
            "Cache-Control": "no-store",
        },
    )


@public_router.get("/sync/{job_id}")
async def get_sync(job_id: str):
    job = await jobs_collection.find_one({"job_id": job_id})
    if not job or "pages" not in job:
        raise HTTPException(status_code=404, detail="Sync info not available")

    return JSONResponse({"pages": job["pages"]})
