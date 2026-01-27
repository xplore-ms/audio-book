import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Query, Request, UploadFile, File, HTTPException, Depends, Form

from core.rate_limiter import rate_limit
from core.dependencies import get_current_user
from credits.service import  (
    UPLOAD_COST,
    add_credits,
    deduct_credits_atomic,
    PAGE_COST
)
from supabase_client import delete_file, upload_bytes
from pdf_utils import get_num_pages_from_bytes
from mongo import jobs_collection
from celery import Celery
from core.config import MAX_PAGES_PER_JOB, MAX_UPLOAD_SIZE, MAX_PAGES
import os
from dotenv import load_dotenv
from pydantic import BaseModel

class UpdateJobRequest(BaseModel):
    title: str
# -----------------------------
# Utilities for TTS sync
# -----------------------------


load_dotenv()
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
router = APIRouter(prefix="", tags=["Jobs"])

celery = Celery("worker")
celery.config_from_object("celeryconfig")


@router.post("/upload")
async def upload_pdf(
    request: Request,
    title: str = Form(...),
    file: UploadFile = File(...),
    user=Depends(get_current_user)
):
    rate_limit(
        key=f"upload:{user['_id']}:{request.client.host}",
        limit=3,
        window_seconds=60
    )
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF allowed")

    if file.content_type != "application/pdf":
        raise HTTPException(400, "Only PDF allowed")

    pdf_bytes = await file.read()

    if not pdf_bytes.startswith(b"%PDF"):
        raise HTTPException(400, "Invalid PDF file")

    if len(pdf_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(400, "File too large")

    job_id = str(uuid.uuid4())
    created_at = datetime.utcnow()
    expires_at = created_at + timedelta(days=5)

    folder = f"{created_at.strftime('%Y%m%d')}_{job_id}"
    remote_pdf = f"pdfs/{folder}/original.pdf"

    original_file_name = file.filename

    
    pages = get_num_pages_from_bytes(pdf_bytes)
    if pages > MAX_PAGES:
        raise HTTPException(400, "Page limit exceeded")

    deduct_credits_atomic(user["_id"], UPLOAD_COST)

    try:
        upload_bytes(remote_pdf, pdf_bytes, "application/pdf")
        jobs_collection.insert_one({
            "job_id": job_id,
            "user_id": str(user["_id"]),
            "email": user["email"],
            "title": title,
            "file_name": original_file_name,
            "remote_pdf_path": remote_pdf,
            "folder_name": folder,
            "num_pages": pages,
            "digits": len(str(pages)),
            "created_at": created_at,
            "expires_at": expires_at,
            "status": "uploaded"
        })
    except Exception:
        add_credits(user["_id"], UPLOAD_COST)
        raise



    return {
        "job_id": job_id,
        "pages": pages,
        "title": title,
        "file_name": original_file_name,
        "expires_at": expires_at
    }

@router.get("/job/{job_id}")
async def get_job(
    job_id: str,
    user=Depends(get_current_user)
):
    job = jobs_collection.find_one({
        "job_id": job_id,
        "user_id": str(user["_id"])
    })

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job["job_id"],
        "pages": job["num_pages"],
        "title": job["title"],
        "file_name": job["file_name"],
        "created_at": job["created_at"],
    }

@router.post("/job/{job_id}/reupload")
async def reupload_pdf(
    request: Request,
    job_id: str,
    file: UploadFile = File(...),
    user=Depends(get_current_user)
):
    rate_limit(
        key=f"upload:{user['_id']}:{request.client.host}",
        limit=2,
        window_seconds=60
    )

    # 1. Validate file
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF allowed")

    if file.content_type != "application/pdf":
        raise HTTPException(400, "Only PDF allowed")

    pdf_bytes = await file.read()

    if not pdf_bytes.startswith(b"%PDF"):
        raise HTTPException(400, "Invalid PDF file")

    if len(pdf_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(400, "File too large")

    # 2. Find job (ownership check)
    job = jobs_collection.find_one({
        "job_id": job_id,
        "user_id": str(user["_id"])
    })

    if not job:
        raise HTTPException(404, "Job not found")

    # 3. Upload to SAME folder & SAME path
    pages = get_num_pages_from_bytes(pdf_bytes)

    if pages > MAX_PAGES:
        raise HTTPException(400, "Page limit exceeded")
    
    remote_pdf = job["remote_pdf_path"]
    deduct_credits_atomic(user["_id"], UPLOAD_COST)

    try:
        upload_bytes(remote_pdf, pdf_bytes, "application/pdf")
        jobs_collection.update_one(
            {"job_id": job_id},
            {"$set": {
                "file_name": file.filename,
                "num_pages": pages,
                "digits": len(str(pages)),
                "updated_at": datetime.utcnow(),
                "reuploaded": True,
                "status": "uploaded"
            }}
        )
    except Exception:
        add_credits(user["_id"], UPLOAD_COST)
        raise



    # 5. Update job metadata

    return {
        "job_id": job_id,
        "pages": pages,
        "file_name": file.filename,
        "message": "PDF re-uploaded successfully"
    }


@router.patch("/job/{job_id}")
async def update_job(
    job_id: str,
    payload: UpdateJobRequest,
    user=Depends(get_current_user)
):
    result = jobs_collection.update_one(
        {"job_id": job_id, "user_id": str(user["_id"])},
        {"$set": {"title": payload.title}}
    )

    if result.matched_count == 0:
        raise HTTPException(404, "Job not found")

    return {"message": "Job updated successfully"}

@router.post("/start")
def start_job(
    job_id: str,
    start: int = 1,
    end: int | None = None,
    user=Depends(get_current_user)
):
    rate_limit(
        key=f"start:{user['_id']}",
        limit=5,
        window_seconds=3600
    )
    job = jobs_collection.find_one_and_update(
        {
            "job_id": job_id,
            "user_id": str(user["_id"]),
            "status": "uploaded"
        },
        {
            "$set": {
                "status": "processing",
                "started_at": datetime.utcnow()
            }
        }
    )

    if not job:
        raise HTTPException(400, "Job already started")


    total = job["num_pages"]
    end = end or total
    pages = end - start + 1
    total_cost = PAGE_COST * pages
    if start < 1 or end > total or start > end:
        raise HTTPException(400, "Invalid page range")

    if pages > MAX_PAGES_PER_JOB:
        raise HTTPException(400, "Page limit exceeded")

    deduct_credits_atomic(user["_id"], total_cost)
    

    task_ids = []
    try:
        for page in range(start, end + 1):
            res =celery.send_task(
                "tasks.process_page",
                args=[job_id, job["remote_pdf_path"], page]
            )
            task_ids.append(res.id)
        jobs_collection.update_one(
            {"job_id": job_id, "status": "uploaded"},
            {"$set": {
                "status": "processing",
                "started_at": datetime.utcnow(),
                "task_ids": task_ids
            }}
        )
    except Exception:
        add_credits(user["_id"], total_cost)
        raise

    return {
        "status": "processing", 
        "pages": pages,
        "job_id": job_id,
        "task_ids": task_ids,
    }

@router.post("/request-full-review")
def request_full_review(
    job_id: str,
    user=Depends(get_current_user)
):
    job = jobs_collection.find_one({"job_id": job_id, "user_id": str(user["_id"])})
    if not job:
        raise HTTPException(404, "Job not found")

    if job.get("review_required"):
        raise HTTPException(400, "Review already requested")

    jobs_collection.update_one(
        {"job_id": job_id},
        {"$set": {
            "review_required": True,
            "review_status": "pending",
            "requested_at": datetime.utcnow()
        }}
    )

    # 🔥 SEND EMAIL ASYNC (NO BLOCKING)
    celery.send_task(
        "tasks.send_review_request_email",
        args=[job_id]
    )

    return {
        "status": "queued_for_review",
        "job_id": job_id
    }


@router.get("/status/{task_id}")
def get_status(
    task_id: str,
    user=Depends(get_current_user)
):
    job = jobs_collection.find_one({
        "task_ids": task_id,
        "user_id": str(user["_id"])
    })

    if not job:
        raise HTTPException(403, "Not authorized")

    async_result = celery.AsyncResult(task_id)

    return {
        "state": async_result.state, 
        "result": async_result.result
    }

@router.get("/me/activity")
def my_activity(user=Depends(get_current_user)):
    jobs = jobs_collection.find(
        {"user_id": str(user["_id"])},
        {"_id": 0, "job_id": 1, "num_pages": 1, "created_at": 1, "review_status": 1}
    )

    return {
        "email": user["email"],
        "credits": user["credits"],
        "jobs": list(jobs)
    }

CLEANUP_SECRET_KEY="my_cron_secret"
@router.post("/cleanup-expired-files")
def cleanup_expired_files(key: str = Query(..., description="Secret key to authorize cleanup")):
    """
    Delete expired PDF files from Supabase.
    Only expires_at < now. Does NOT delete MongoDB records.
    Use secret key to call from external cron.
    """
    if key != CLEANUP_SECRET_KEY:
        raise HTTPException(403, "Not authorized")

    now = datetime.utcnow()
    expired_jobs = jobs_collection.find({"expires_at": {"$lt": now}})
    
    deleted_count = 0
    errors = []

    for job in expired_jobs:
        remote_path = job.get("remote_pdf_path")
        if not remote_path:
            continue
        
        try:
            delete_file(remote_path)
            deleted_count += 1
        except Exception as e:
            errors.append({"job_id": job.get("job_id"), "error": str(e)})
            continue

    return {
        "status": "done",
        "deleted_files": deleted_count,
        "errors": errors
    }
