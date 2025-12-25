from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from mongo import jobs_collection, users_collection
from supabase_client import upload_bytes, download_to_bytes, get_url, list_files
from core.security import (
    hash_password,
    verify_password,
    create_access_token
)
from pdf_utils import get_num_pages_from_bytes
from core.dependencies import get_current_user
from celery import Celery
from datetime import datetime
import uuid

router = APIRouter(prefix="/admin", tags=["Admin"])

celery = Celery("worker")
SUPABASE_ADMIN_FOLDER = "admin_library"
MAX_PAGES_AT_ONCE = 50  # safety limit for batch processing

def make_folder_name(job_id: str) -> str:
    return f"{datetime.utcnow().strftime('%Y%m%d')}_{job_id}"


# -------------------------
# ADMIN: Upload PDF + specify credits
# -------------------------
@router.post("/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    required_credits: int = Form(1),
    user=Depends(get_current_user)
):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF allowed")

    pdf_bytes = await file.read()
    job_id = str(uuid.uuid4())
    folder_name = make_folder_name(job_id)
    remote_path = f"{SUPABASE_ADMIN_FOLDER}/pdfs/{folder_name}/original.pdf"

    # Upload PDF to Supabase
    upload_bytes(remote_path, pdf_bytes, "application/pdf")

    # Count pages
    num_pages = get_num_pages_from_bytes(pdf_bytes)
    digits = len(str(num_pages))

    # Save metadata
    jobs_collection.insert_one({
        "job_id": job_id,
        "user_id": user["_id"],
        "is_admin": True,
        "folder_name": folder_name,
        "remote_pdf_path": remote_path,
        "num_pages": num_pages,
        "digits": digits,
        "required_credits": required_credits,  # credits required to listen
        "sync": {},  # placeholder for per-page sync timestamps
        "created_at": datetime.utcnow()
    })

    return {
        "job_id": job_id,
        "folder_name": folder_name,
        "remote_pdf_path": remote_path,
        "num_pages": num_pages,
        "digits": digits,
        "required_credits": required_credits
    }


# -------------------------
# ADMIN: Start processing PDF → audio
# -------------------------
@router.post("/process-job")
def start_admin_job(
    job_id: str = Form(...),
    start: int = Form(1),
    end: int = Form(None),
    user=Depends(get_current_user)
):
    """
    Trigger Celery tasks to process admin job pages.
    Allows start/end to prevent Redis/worker crash.
    No credit deduction.
    """
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    job = jobs_collection.find_one({"job_id": job_id, "is_admin": True})
    if not job:
        raise HTTPException(status_code=404, detail="Admin job not found")

    total_pages = job.get("num_pages", 0)
    end = end or total_pages

    if start < 1 or end > total_pages or start > end:
        raise HTTPException(status_code=400, detail="Invalid page range")

    pages_requested = end - start + 1
    if pages_requested > MAX_PAGES_AT_ONCE:
        raise HTTPException(
            status_code=400,
            detail=f"Too many pages requested at once ({pages_requested}). "
                   f"Max allowed per batch: {MAX_PAGES_AT_ONCE}"
        )

    # Trigger Celery tasks for each page
    task_ids = []
    for page in range(start, end + 1):
        task = celery.send_task(
            "tasks.process_page_with_sync",
            args=[job_id, job["remote_pdf_path"], page]
        )
        task_ids.append(task.id)

    return {
        "job_id": job_id,
        "task_ids": task_ids,
        "pages_processing": pages_requested,
        "total_pages": total_pages
    }


# -------------------------
# ADMIN: List completed audiobooks
# -------------------------
@router.get("/my")
def my_library(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    jobs = jobs_collection.find(
        {"user_id": user["_id"], "is_admin": True, "final_parts": {"$exists": True}},
        {"_id": 0, "job_id": 1, "final_parts": 1, "final_size_mb": 1, "required_credits": 1}
    )
    return list(jobs)

# -------------------------
# PUBLIC: List all audiobooks
# -------------------------
public_router = APIRouter(prefix="/public", tags=["Public Library"])

@public_router.get("/")
def list_public_audios():
    """
    Return all audiobooks from admin library that are ready
    """
    jobs = jobs_collection.find(
        {"is_admin": True, "final_parts": {"$exists": True}},
        {"_id": 0, "job_id": 1, "final_parts": 1, "final_size_mb": 1, "required_credits": 1}
    )
    return list(jobs)


# -------------------------
# PUBLIC: Stream audio (requires credits)
# -------------------------
@public_router.get("/listen/{job_id}")
def stream_public_audio(job_id: str, user=Depends(get_current_user)):
    job = jobs_collection.find_one({"job_id": job_id, "is_admin": True})
    if not job or "final_parts" not in job:
        raise HTTPException(status_code=404, detail="Audio not found")

    user_doc = users_collection.find_one({"_id": user["_id"]})
    user_credits = user_doc.get("credits", 0)
    required = job.get("required_credits", 1)

    if user_credits < required:
        raise HTTPException(
            status_code=403,
            detail=f"Not enough credits. Required: {required}, you have: {user_credits}"
        )

    # Deduct credits
    users_collection.update_one(
        {"_id": user["_id"]},
        {"$inc": {"credits": -required}}
    )

    final_parts = job["final_parts"]

    def extract_storage_path(public_url: str) -> str:
        marker = f"/storage/v1/object/public/admin_library/"
        if marker not in public_url:
            raise RuntimeError("Invalid Supabase public URL format")
        return public_url.split(marker, 1)[1]

    def audio_generator():
        for idx, public_url in enumerate(final_parts):
            storage_path = extract_storage_path(public_url)
            audio_bytes = download_to_bytes(storage_path)
            if idx > 0:
                audio_bytes = audio_bytes[44:]  # strip WAV header
            yield audio_bytes

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        audio_generator(),
        media_type="audio/wav",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": "inline; filename=audiobook.wav"
        }
    )

@router.get("/reviews")
def list_review_requests(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    pipeline = [
        {
            "$match": {
                "review_required": True,
                "review_status": "pending",
                "is_admin": {"$ne": True}
            }
        },
        {
            "$lookup": {
                "from": "users",
                "localField": "user_id",
                "foreignField": "_id",
                "as": "user"
            }
        },
        {"$unwind": "$user"},
        {
            "$project": {
                "_id": 0,
                "job_id": 1,
                "num_pages": 1,
                "requested_at": 1,
                "user_email": "$user.email",
                "user_credits": "$user.credits"
            }
        }
    ]

    return list(jobs_collection.aggregate(pipeline))

@router.post("/create-admin")
def create_admin_user(
    email: str = Form(...),
    password: str = Form(...),
    user=Depends(get_current_user)
):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    if users_collection.find_one({"email": email}):
        raise HTTPException(400, "Email already exists")

    users_collection.insert_one({
        "email": email,
        "password_hash": hash_password(password),
        "credits": 0,
        "role": "admin",
        "created_at": datetime.utcnow()
    })

    return {"message": "Admin user created successfully"}

@router.post("/login")
def admin_login(
    email: str = Form(...),
    password: str = Form(...)
):
    admin = users_collection.find_one({
        "email": email,
        "role": "admin"
    })

    if not admin:
        raise HTTPException(status_code=401, detail="Invalid admin credentials")

    if not verify_password(password, admin["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid admin credentials")

    token = create_access_token(email)

    return {
        "access_token": token,
        "token_type": "bearer",
        "role": "admin"
    }
# -------------------------
# PUBLIC: Fetch sync timestamps
# -------------------------
@public_router.get("/sync/{job_id}")
def get_sync(job_id: str):
    job = jobs_collection.find_one({"job_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.get("sync", {})  # per-page timestamp sync

@public_router.get("/sync/global/{job_id}")
def get_global_sync(job_id: str):
    job = jobs_collection.find_one({"job_id": job_id})
    if not job or "global_sync_url" not in job:
        raise HTTPException(status_code=404, detail="Global sync not available")
    return {"global_sync_url": job["global_sync_url"]}
