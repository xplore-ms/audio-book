import time
from fastapi import APIRouter, HTTPException, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse, JSONResponse
from app.integrations.supabase.client import _safe_create_signed_url, download_to_bytes, _safe_create_download_url
from app.core.dependencies import get_current_user, get_current_user_from_query, oauth2_scheme
from pydantic import BaseModel, EmailStr
from typing import List
from datetime import datetime

from app.db.mongo import jobs_collection
import io
import os
import wave
from dotenv import load_dotenv

load_dotenv()
router = APIRouter(prefix="/audio", tags=["Audio"])
WAV_HEADER_SIZE = 44

from app.core import config

SUPABASE_BUCKET = config.SUPABASE_BUCKET

class ShareWithEmailsPayload(BaseModel):
    emails: List[EmailStr]

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


@router.get("/pages/{job_id}")
def get_pages(
    job_id: str, 
    request: Request,
    skip: int = 0, 
    limit: int = 5, 
    user=Depends(get_current_user),
    token: str = Depends(oauth2_scheme)
):
    job = jobs_collection.find_one({"job_id": job_id})
    if not job or "pages" not in job:
        raise HTTPException(404, "Pages not found")

    if job["user_id"] != str(user["_id"]):
        if job.get("shared") is not True:
            raise HTTPException(403, "Access denied")

        shared_emails = [
            s["email"] for s in job.get("shared_with", [])
        ]

        if user["email"].lower() not in shared_emails:
            raise HTTPException(403, "Access denied")


    pages = job.get("pages", {})
    
    # Sort keys
    try:
        ordered_keys = sorted(pages.keys(), key=lambda k: int(k.split("_")[-1]))
    except ValueError:
        # Fallback for irregular keys
        ordered_keys = sorted(pages.keys())

    # Paginate
    paged_keys = ordered_keys[skip : skip + limit]

    playlist = []
    now = int(time.time())
    expires_at = now + 900  # 5 minutes TTL for signed URLs

    for key in paged_keys:
        page = pages[key]
        
        # Support both legacy audio_path and new hls_path
        audio_path = page.get("audio_path")
        hls_path = page.get("hls_path")
        
        final_path = audio_path or hls_path
        
        if not final_path:
            continue

        if hls_path:
            # Use backend proxy for HLS to handle segment signing
            # Construct absolute URL to our HLS endpoint
            base_url = str(request.base_url).rstrip("/")
            audio_url = f"{base_url}/api/v1/audio/hls/{job_id}/{key}/playlist.m3u8?token={token}"
        else:
            # Fallback for legacy single file
            audio_url = _safe_create_signed_url(final_path, 900)
        
        download_url = None
        # Only create download link for single file audio
        if audio_path:
            download_url = _safe_create_download_url(
                audio_path,
                900,
                filename=f"{job.get('title', 'audio')}_{key}.mp3"
            )
        
        sync_url = _safe_create_signed_url(page["sync_path"], 900) if page.get("sync_path") else None

        playlist.append({
            "page": key,
            "audio_url": audio_url,
            "download_url": download_url,
            "sync_url": sync_url,
            "duration": page.get("duration", 0),
            "expires_at": expires_at
        })

    return {
        "job_id": job.get("job_id"),
        "title": job.get("title"),
        "pages": playlist,
        "total_pages": len(ordered_keys),
        "skip": skip,
        "limit": limit
    }


@router.post("/share/{job_id}/emails")
def share_audiobook_with_emails(
    job_id: str,
    payload: ShareWithEmailsPayload,
    user=Depends(get_current_user)
):
    result = jobs_collection.update_one(
        {"job_id": job_id, "user_id": str(user["_id"])},
        {
            "$set": {"shared": True},
            "$addToSet": {
                "shared_with": {
                    "$each": [
                        {
                            "email": email.lower(),
                            "added_at": datetime.utcnow()
                        }
                        for email in payload.emails
                    ]
                }
            }
        }
    )

    if result.matched_count == 0:
        raise HTTPException(404, "Job not found")

    return {
        "message": "Audiobook shared successfully",
        "shared_with": payload.emails
    }


@router.get("/unshare/{job_id}")
def unshare_audiobook(job_id: str, user=Depends(get_current_user)):
    result = jobs_collection.update_one(
        {"job_id": job_id, "user_id": str(user["_id"])},
        {"$set": {"shared": False}}
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Job not found")

    return {"message": "Job updated successfully"}


@router.get("/hls/{job_id}/{page_key}/playlist.m3u8")
def get_hls_playlist(
    job_id: str,
    page_key: str,
    token: str = Query(...),
    user=Depends(get_current_user_from_query)
):
    """
    Serve HLS playlist with signed segment URLs.
    """
    job = jobs_collection.find_one({"job_id": job_id})
    if not job:
        raise HTTPException(404, "Job not found")

    # Check access (same logic as get_pages)
    if job["user_id"] != str(user["_id"]):
        if job.get("shared") is not True:
            raise HTTPException(403, "Access denied")
        
        shared_emails = [s["email"] for s in job.get("shared_with", [])]
        if user["email"].lower() not in shared_emails:
            raise HTTPException(403, "Access denied")

    pages = job.get("pages", {})
    if page_key not in pages:
        raise HTTPException(404, "Page not found")

    page = pages[page_key]
    hls_path = page.get("hls_path")
    
    if not hls_path:
        raise HTTPException(404, "HLS content not found for this page")

    # Fetch original playlist from Supabase
    try:
        content_bytes = download_to_bytes(hls_path)
        content_str = content_bytes.decode("utf-8")
    except Exception as e:
        print(f"Failed to download playlist: {e}")
        raise HTTPException(500, "Failed to retrieve playlist")

    # Parse and rewrite
    lines = content_str.splitlines()
    new_lines = []
    
    # Base directory for segments (same as playlist)
    # Use string manipulation to ensure forward slashes (Supabase requires them)
    if "/" in hls_path:
        base_dir = hls_path.rsplit("/", 1)[0]
    else:
        base_dir = ""

    for line in lines:
        if line.strip().endswith(".aac") or line.strip().endswith(".ts"):
            # It's a segment
            segment_filename = line.strip()
            if base_dir:
                segment_path = f"{base_dir}/{segment_filename}"
            else:
                segment_path = segment_filename
                
            # Generate signed URL for segment
            signed_url = _safe_create_signed_url(segment_path, 3600) # 1 hour validity
            if signed_url:
                new_lines.append(signed_url)
            else:
                # If signing fails, keep original (will likely fail client-side but better than nothing)
                new_lines.append(line)
        else:
            new_lines.append(line)

    modified_playlist = "\n".join(new_lines)

    return Response(content=modified_playlist, media_type="application/vnd.apple.mpegurl")
