import uuid
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends

from core.dependencies import get_current_user
from credits.service import  (
    require_credits,
    deduct_credits,
    UPLOAD_COST,
    PAGE_COST
)
from supabase_client import upload_bytes
from pdf_utils import get_num_pages_from_bytes
from mongo import jobs_collection
from celery import Celery
from core.config import MAX_UPLOAD_SIZE, MAX_PAGES
import os
from dotenv import load_dotenv

# -----------------------------
# Utilities for TTS sync
# -----------------------------

from email_utils import send_email

load_dotenv()
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
router = APIRouter(prefix="", tags=["Jobs"])

celery = Celery("worker")
celery.config_from_object("celeryconfig")

@router.post("/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    user=Depends(get_current_user)
):
    require_credits(user, UPLOAD_COST)

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF allowed")

    pdf_bytes = await file.read()
    if len(pdf_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(400, "File too large")

    job_id = str(uuid.uuid4())
    folder = f"{datetime.utcnow().strftime('%Y%m%d')}_{job_id}"
    remote_pdf = f"pdfs/{folder}/original.pdf"

    upload_bytes(remote_pdf, pdf_bytes, "application/pdf")
    pages = get_num_pages_from_bytes(pdf_bytes)

    jobs_collection.insert_one({
        "job_id": job_id,
        "user_id": user["_id"],
        "remote_pdf_path": remote_pdf,
        "email": user["email"],
        "folder_name": folder,
        "num_pages": pages,
        "digits": len(str(pages)),
        "created_at": datetime.utcnow()
    })

    deduct_credits(user, UPLOAD_COST)

    return {"job_id": job_id, "pages": pages}

@router.post("/start")
def start_job(
    job_id: str,
    start: int = 1,
    end: int | None = None,
    user=Depends(get_current_user)
):
    job = jobs_collection.find_one({"job_id": job_id, "user_id": user["_id"]})
    if not job:
        raise HTTPException(404, "Job not found")

    total = job["num_pages"]
    end = end or total
    pages = end - start + 1

    if pages > MAX_PAGES:
        raise HTTPException(400, "Page limit exceeded")

    require_credits(user, PAGE_COST * pages)
    deduct_credits(user, PAGE_COST * pages)

    task_ids = []
    for page in range(start, end + 1):
        res =celery.send_task(
            "tasks.process_page",
            args=[job_id, job["remote_pdf_path"], page]
        )
        task_ids.append(res.id)

    # 🔥 AUTO MERGE
    celery.send_task("tasks.merge_pages", args=[job_id])

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
    job = jobs_collection.find_one({"job_id": job_id, "user_id": user["_id"]})
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
def get_status(task_id: str):
    async_result = celery.AsyncResult(task_id)
    return {"state": async_result.state, "result": async_result.result}


@router.get("/me/activity")
def my_activity(user=Depends(get_current_user)):
    jobs = jobs_collection.find(
        {"user_id": user["_id"]},
        {"_id": 0, "job_id": 1, "num_pages": 1, "created_at": 1, "review_status": 1}
    )

    return {
        "email": user["email"],
        "credits": user["credits"],
        "jobs": list(jobs)
    }
