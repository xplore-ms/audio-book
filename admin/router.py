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
celery.config_from_object("celeryconfig")

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

    job = jobs_collection.find_one({"job_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Admin job not found")

    # Block processing if review is required but not approved
    if job.get("review_required") and job.get("review_status") != "approved":
        raise HTTPException(
            status_code=403,
            detail="Job requires admin approval before processing"
        )

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
            "tasks.process_page",
            args=[job_id, job["remote_pdf_path"], page]
        )
        task_ids.append(task.id)

    return {
        "job_id": job_id,
        "task_ids": task_ids,
        "pages_processing": pages_requested,
        "total_pages": total_pages
    }

@router.get("/metrics/overview")
def admin_metrics_overview(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")

    total_users = users_collection.count_documents({})
    total_jobs = jobs_collection.count_documents({})

    users_with_credits = users_collection.count_documents({
        "credits": {"$gt": 0}
    })

    review_pending = jobs_collection.count_documents({
        "review_status": "pending"
    })

    review_done = jobs_collection.count_documents({
        "review_status": "done"
    })

    return {
        "users": {
            "total": total_users,
            "with_credits": users_with_credits
        },
        "jobs": {
            "total": total_jobs,
            "review_pending": review_pending,
            "review_done": review_done
        }
    }

from datetime import timedelta

@router.get("/metrics/users")
def admin_user_metrics(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")

    now = datetime.utcnow()

    last_7_days = users_collection.count_documents({
        "created_at": {"$gte": now - timedelta(days=7)}
    })

    last_30_days = users_collection.count_documents({
        "created_at": {"$gte": now - timedelta(days=30)}
    })

    total_credits = list(users_collection.aggregate([
        {"$group": {"_id": None, "total": {"$sum": "$credits"}}}
    ]))

    total_credits = total_credits[0]["total"] if total_credits else 0

    return {
        "new_users": {
            "last_7_days": last_7_days,
            "last_30_days": last_30_days
        },
        "credits": {
            "total_remaining": total_credits
        }
    }

@router.get("/metrics/activity")
def admin_activity_metrics(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")

    pipeline = [
        {
            "$group": {
                "_id": "$user_id",
                "jobs_created": {"$sum": 1},
                "pages": {"$sum": "$num_pages"}
            }
        },
        {
            "$sort": {"jobs_created": -1}
        },
        {
            "$limit": 10
        }
    ]

    top_users = list(jobs_collection.aggregate(pipeline))

    return {
        "top_active_users": [
            {
                "user_id": str(u["_id"]),
                "jobs_created": u["jobs_created"],
                "pages_processed": u["pages"]
            }
            for u in top_users
        ]
    }


@router.post("/approve-review")
def approve_review(
    job_id: str = Form(...),
    user=Depends(get_current_user)
):
    # Admin only
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    job = jobs_collection.find_one({
        "job_id": job_id,
        "review_required": True,
        "review_status": "pending"
    })

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Pending review job not found"
        )

    jobs_collection.update_one(
        {"job_id": job_id},
        {"$set": {
            "review_status": "approved",
            "review_approved_at": datetime.utcnow(),
            "review_approved_by": user["_id"]
        }}
    )

    return {
        "status": "approved",
        "job_id": job_id
    }

@router.post("/process-done")
def done_processing(
    job_id: str = Form(...),
    user=Depends(get_current_user)
):
    # Admin only
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    job = jobs_collection.find_one({
        "job_id": job_id,
        "review_required": True
    })

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.get("review_status") != "approved":
        raise HTTPException(
            status_code=400,
            detail="Job is not in approved state"
        )

    jobs_collection.update_one(
        {"job_id": job_id},
        {"$set": {
            "review_status": "done",
            "review_done_at": datetime.utcnow(),
            "review_done_by": user["_id"]
        }}
    )

    return {
        "status": "done",
        "job_id": job_id
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

@router.get("/reviews")
def list_review_requests(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    pipeline = [
        {
            "$match": {
                "review_required": True,
                "review_status": {"$in": ["pending", "approved", "done"]},
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
                "review_status": 1,        # 👈 important for frontend
                "user_email": "$user.email",
                "user_credits": "$user.credits"
            }
        },
        {
            "$sort": {"requested_at": -1}  # 👈 newest first (recommended)
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
