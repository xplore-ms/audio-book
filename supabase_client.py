# supabase_client.py
import os
from dotenv import load_dotenv
load_dotenv()

from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "reading_app")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def upload_bytes(path: str, data: bytes, content_type="application/octet-stream") -> str:
    # Supabase storage.upload accepts path, fileobj or bytes depending on version
    supabase.storage.from_(SUPABASE_BUCKET).upload(path, data, {"content-type": content_type})
    return get_url(path)

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

def get_url(remote_path: str) -> str:
    resp = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(remote_path)
    if isinstance(resp, dict):
        # support different keys
        return resp.get("publicUrl") or resp.get("public_url") or resp.get("publicURL")
    return str(resp)

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