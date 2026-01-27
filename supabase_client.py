# supabase_client.py
import os
import time
from dotenv import load_dotenv
load_dotenv()

import httpx
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "reading_app")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def create_signed_url(path: str, expires_in: int = 300) -> str:
    """
    Create a signed URL for a private Supabase object.
    """
    res = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(
        path,
        expires_in
    )

    if isinstance(res, dict):
        return res.get("signedURL") or res.get("signed_url")

    raise RuntimeError("Failed to create signed URL")

def upload_bytes(path: str, data: bytes, content_type="application/octet-stream"):
    supabase.storage.from_(SUPABASE_BUCKET).upload(
        path,
        data,
        {"content-type": content_type}
    )
    return path  # RETURN PATH, NOT URL


def upload_file(local_path: str, remote_path: str, content_type="application/octet-stream") -> str:
    with open(local_path, "rb") as f:
        data = f.read()
    return upload_bytes(remote_path, data, content_type)

def download_to_bytes(remote_path: str) -> bytes:
    res = supabase.storage.from_(SUPABASE_BUCKET).download(remote_path)
    # handle possible return shapes
    if isinstance(res, (bytes, bytearray)):
        return bytes(res)
    if hasattr(res, "content"):
        return res.content
    if hasattr(res, "read"):
        return res.read()
    raise RuntimeError("Unsupported supabase download response type")

# def get_url(remote_path: str) -> str:
#     resp = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(remote_path)
#     if isinstance(resp, dict):
#         # support different keys
#         return resp.get("publicUrl") or resp.get("public_url") or resp.get("publicURL")
#     return str(resp)

import time
from typing import Optional

def _safe_create_signed_url(path: str, ttl: int) -> Optional[str]:
    """
    Create a signed URL safely with minimal retry.
    Returns None if it fails.
    """
    try:
        res = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(path, ttl)
        return res.get("signedURL") or res.get("signed_url")
    except Exception:
        # One lightweight retry (new TLS connection)
        try:
            res = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(path, ttl)
            return res.get("signedURL") or res.get("signed_url")
        except Exception as e:
            print(f"[SignedURL] Failed for {path}: {e}")
            return None


def build_playlist_response(job: dict, signed_url_ttl: int = 300):
    pages = job.get("pages", {})

    def page_sort_key(k: str) -> int:
        return int(k.split("_")[-1])

    ordered_keys = sorted(pages.keys(), key=page_sort_key)

    now = int(time.time())
    expires_at = now + signed_url_ttl

    playlist = []

    for key in ordered_keys:
        page = pages[key]

        audio_path = page.get("audio_path")
        if not audio_path:
            continue

        audio_url = _safe_create_signed_url(audio_path, signed_url_ttl)
        if not audio_url:
            # Skip page if audio URL fails
            continue

        sync_url = None
        sync_path = page.get("sync_path")
        if sync_path:
            sync_url = _safe_create_signed_url(sync_path, signed_url_ttl)

        playlist.append({
            "page": key,
            "audio_url": audio_url,
            "sync_url": sync_url,
            "duration": page.get("duration", 0),
            "expires_at": expires_at
        })

    return {
        "job_id": job.get("job_id"),
        "title": job.get("title"),
        "pages": playlist
    }


def list_files(folder: str):
    """
    List files in Supabase storage folder robustly.
    Returns list of metadata dicts.
    """
    if not folder.endswith("/"):
        folder = folder + "/"

    # Try simple list first
    try:
        result = supabase.storage.from_(SUPABASE_BUCKET).list(folder)
        return result or []
    except Exception:
        # fallback to paginated listing if client supports 'limit' and 'offset'
        items = []
        limit = 1000
        offset = 0
        while True:
            try:
                batch = supabase.storage.from_(SUPABASE_BUCKET).list(folder, {"limit": limit, "offset": offset})
            except Exception:
                # if vendor client doesn't support offset, re-raise original
                break
            if not batch:
                break
            items.extend(batch)
            if len(batch) < limit:
                break
            offset += limit
        return items

def extract_storage_path(public_url: str) -> str:
    marker = f"/storage/v1/object/public/{SUPABASE_BUCKET}/"
    if marker not in public_url:
        raise ValueError("Invalid Supabase public URL")
    return public_url.split(marker, 1)[1]

def delete_file(path: str) -> bool:
    """
    Delete a single file from Supabase storage.
    Returns True if deleted successfully, False otherwise.
    """
    try:
        # Supabase expects a list of paths
        res = supabase.storage.from_(SUPABASE_BUCKET).remove([path])
        # `res` is usually a list of removed file info; empty list means success
        return True
    except Exception as e:
        print(f"[Supabase] Failed to delete {path}: {e}")
        return False


def delete_folder(folder: str) -> dict:
    """
    Delete all files in a folder from Supabase storage.
    Returns a dict with {deleted: [...], failed: [...]}.
    """
    if not folder.endswith("/"):
        folder = folder + "/"

    deleted = []
    failed = []

    files = list_files(folder)
    for file in files:
        # Each file item has a 'name' field with the full path relative to bucket
        file_path = file.get("name") or file.get("path") or file
        if delete_file(file_path):
            deleted.append(file_path)
        else:
            failed.append(file_path)

    return {"deleted": deleted, "failed": failed}
