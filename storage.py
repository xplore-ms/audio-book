# app/storage.py
import os
import shutil
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

# Config
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "reading_app")
STORAGE_DIR = os.getenv("STORAGE_DIR", "./storage")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in .env")

# Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# --- Local storage helpers (still useful for temp files) ---
def ensure_storage_dir():
    os.makedirs(STORAGE_DIR, exist_ok=True)


def cleanup_file(path: str):
    """Delete a single file if it exists."""
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def cleanup_folder(path: str):
    """Delete a folder recursively."""
    try:
        if os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


# --- Upload a local file (path) to Supabase ---
def upload_file_to_supabase(local_path: str, remote_path: str, content_type: str = None) -> str:
    """
    Upload a local file to Supabase storage and return a public URL.
    local_path: path on disk
    remote_path: e.g. "pdfs/job_id/audio/page_7.mp3"
    """
    if not os.path.exists(local_path):
        raise FileNotFoundError(f"Local file not found: {local_path}")

    with open(local_path, "rb") as f:
        # supabase-py accepts file-like; some versions accept bytes directly
        data = f.read()

    file_options = None
    if content_type:
        file_options = {"content-type": content_type}

    # upload — depending on client version, .upload may accept bytes or file-like
    supabase.storage.from_(SUPABASE_BUCKET).upload(remote_path, data, file_options)

    # return public url
    return get_public_url(remote_path)


# --- Upload directly from raw file-like object (e.g., UploadFile.file) ---
def upload_raw_file_to_supabase(file_obj, remote_path: str, content_type: str = None) -> str:
    """
    Upload a raw file-like object (UploadFile.file) directly to Supabase.
    file_obj: a file-like object supporting .read()
    """
    # read bytes
    data = file_obj.read()

    file_options = None
    if content_type:
        file_options = {"content-type": content_type}

    supabase.storage.from_(SUPABASE_BUCKET).upload(remote_path, data, file_options)

    return get_public_url(remote_path)


# --- Download a file from Supabase to local path ---
def download_file_from_supabase(remote_path: str, local_path: str) -> None:
    """
    Download a file from Supabase storage to local path.
    remote_path: e.g. "pdfs/job_id/book.pdf" or "pdfs/job_id/audio/page_7.mp3"
    """
    # Some supabase clients return bytes, some return a response-like object.
    res = supabase.storage.from_(SUPABASE_BUCKET).download(remote_path)

    # Ensure dir exists
    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    # Try common response shapes
    if isinstance(res, (bytes, bytearray)):
        content = res
    else:
        # attempt common attributes
        content = None
        if hasattr(res, "content"):
            content = res.content
        elif hasattr(res, "read"):
            try:
                content = res.read()
            except Exception:
                content = None

    if content is None:
        raise RuntimeError("Unsupported supabase .download() response type. Please adapt storage.download_file_from_supabase to your supabase client version.")

    with open(local_path, "wb") as f:
        f.write(content)


# --- Get public URL for a remote object ---
def get_public_url(remote_path: str) -> str:
    """
    Return public URL (string) for remote_path in SUPABASE_BUCKET.
    """
    resp = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(remote_path)
    # supabase-py often returns dict like {'publicUrl': '...'}
    if isinstance(resp, dict):
        for k in ("publicUrl", "public_url", "publicURL"):
            if k in resp:
                return resp[k]
        # fallback to str
        return str(resp)
    return str(resp)