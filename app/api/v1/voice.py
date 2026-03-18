from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from bson.objectid import ObjectId
import time

from app.integrations.supabase.client import _safe_create_signed_url
from app.core.dependencies import get_current_user
from app.db.mongo import voices_collection

router = APIRouter(prefix="/voices", tags=["Voices"])


@router.get("/")
def list_voices(
    user=Depends(get_current_user),
    ttl: int = Query(900, description="Signed URL TTL in seconds"),
):
    docs = list(
        voices_collection.find(
            {},
            {
                "supabase_path": 1,
                "voice_name": 1,
                "display_name": 1,
                "language_codes": 1,
                "ssml_gender": 1,
                "sample_text": 1,
                "engine": 1,
            },
        )
    )

    now = int(time.time())
    expires_at = now + ttl

    out = []
    for d in docs:
        path = d.get("supabase_path")
        url = None
        if path:
            url = _safe_create_signed_url(path, ttl)

        out.append(
            {
                "id": str(d.get("_id")),
                "voice_name": d.get("voice_name"),
                "display_name": d.get("display_name"),
                "language_codes": d.get("language_codes"),
                "ssml_gender": d.get("ssml_gender"),
                "sample_text": d.get("sample_text"),
                "engine": d.get("engine", "google"),
                "supabase_path": path,
                "url": url,
                "expires_at": expires_at if url else None,
            }
        )

    return JSONResponse({"voices": out})


@router.get("/{voice_id}/url")
def get_voice_signed_url(
    voice_id: str, user=Depends(get_current_user), ttl: int = Query(900)
):
    try:
        vid = ObjectId(voice_id)
    except Exception:
        raise HTTPException(400, "Invalid voice id")

    doc = voices_collection.find_one({"_id": vid})
    if not doc:
        raise HTTPException(404, "Voice not found")

    path = doc.get("supabase_path")
    if not path:
        raise HTTPException(404, "Voice file not available")

    url = _safe_create_signed_url(path, ttl)
    if not url:
        raise HTTPException(500, "Failed to create signed URL")

    return {"url": url, "expires_at": int(time.time()) + ttl}
