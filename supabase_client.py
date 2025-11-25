# supabase_client.py
import os
from supabase import create_client, Client
from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "reading_app")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def upload_bytes(path: str, data: bytes, content_type="application/octet-stream") -> str:
    supabase.storage.from_(SUPABASE_BUCKET).upload(
        path, data, {"content-type": content_type}
    )
    return get_url(path)

def upload_file(local_path: str, remote_path: str, content_type="application/octet-stream") -> str:
    with open(local_path, "rb") as f:
        data = f.read()
    return upload_bytes(remote_path, data, content_type)

def download_to_bytes(remote_path: str) -> bytes:
    res = supabase.storage.from_(SUPABASE_BUCKET).download(remote_path)
    if isinstance(res, bytes):
        return res
    if hasattr(res, "content"):
        return res.content
    return res.read()

def get_url(remote_path: str) -> str:
    resp = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(remote_path)
    if isinstance(resp, dict):
        return resp.get("publicUrl") or resp.get("public_url")
    return resp
