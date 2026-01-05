from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from mongo import jobs_collection, users_collection
from supabase_client import upload_bytes
from core.security import (
    hash_password,
    verify_password,
    create_access_token
)
from credits.service import  (
    require_credits,
    deduct_credits,
    PAGE_COST
)
from pdf_utils import get_num_pages_from_bytes
from core.dependencies import get_current_user
from celery import Celery
from datetime import datetime, timedelta
import uuid

router = APIRouter(prefix="/admin", tags=["Admin"])

celery = Celery("worker")
celery.config_from_object("celeryconfig")

SUPABASE_ADMIN_FOLDER = "admin_library"
MAX_PAGES_AT_ONCE = 50  # safety limit for batch processing

REVIEW_TAG = "Review Workflow"
PROCESSING_TAG = "Processing"
EMAIL_TAG = "Email Notifications"
ADMIN_TAG = "Admin"

def make_folder_name(job_id: str) -> str:
    return f"{datetime.utcnow().strftime('%Y%m%d')}_{job_id}"


# -------------------------
# ADMIN: Upload PDF + specify credits
# -------------------------
@router.post("/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    title: str = Form(...),
    category: str = Form(...),
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

    original_file_name = file.filename

    upload_bytes(remote_path, pdf_bytes, "application/pdf")

    # Count pages
    num_pages = get_num_pages_from_bytes(pdf_bytes)
    digits = len(str(num_pages))

    # Save metadata
    jobs_collection.insert_one({
        "job_id": job_id,
        "user_id": str(user["_id"]),
        "is_admin": True,
        "title": title,
        "category": category,
        "file_name": original_file_name,
        "folder_name": folder_name,
        "remote_pdf_path": remote_path,
        "num_pages": num_pages,
        "digits": digits,
        "required_credits": required_credits,  # credits required to listen
        "sync": {},
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

@router.post("/start-admin-job")
def start_job(
    job_id: str,
    start: int = 1,
    end: int | None = None,
    user=Depends(get_current_user)
):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    job = jobs_collection.find_one({"job_id": job_id, "user_id": str(user["_id"])})
    if not job:
        raise HTTPException(404, "Job not found")

    total = job["num_pages"]
    end = end or total
    pages = end - start + 1

    if pages > MAX_PAGES_AT_ONCE:
        raise HTTPException(400, "Page limit exceeded")

    task_ids = []
    for page in range(start, end + 1):
        res =celery.send_task(
            "tasks.process_admin_page",
            args=[job_id, job["remote_pdf_path"], page]
        )
        task_ids.append(res.id)

    return {
        "status": "processing", 
        "pages": pages,
        "job_id": job_id,
        "task_ids": task_ids,
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


# -------------------------
# ADMIN: Start processing PDF → audio
# -------------------------
@router.post("/process-job",
             tags=[ADMIN_TAG, PROCESSING_TAG, EMAIL_TAG])
def start_admin_request_job(
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
        raise HTTPException(status_code=404, detail="User job not found")

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

    celery.send_task(
        "tasks.send_job_state_email",
        args=[job_id, "processing", "Your job has started processing."]
    )

    return {
        "job_id": job_id,
        "task_ids": task_ids,
        "pages_processing": pages_requested,
        "total_pages": total_pages
    }

@router.post("/approve-review",
    tags=[ADMIN_TAG, REVIEW_TAG, EMAIL_TAG])
def approve_review(
    job_id: str = Form(...),
    user=Depends(get_current_user)
):
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

    request_user = users_collection.find_one({"_id": job["user_id"]})
    if not request_user:
        raise HTTPException(
            status_code=404,
            detail="Requesting user not found"
        )
    
    total_cost = PAGE_COST * job["num_pages"]
    require_credits(request_user, total_cost)
    deduct_credits(request_user["_id"], total_cost)

    jobs_collection.update_one(
        {"job_id": job_id},
        {"$set": {
            "review_status": "approved",
            "review_approved_at": datetime.utcnow(),
            "review_approved_by": user["_id"]
        }}
    )

    celery.send_task(
        "tasks.send_job_state_email",
        args=[job_id, "approved", None]
    )

    return {
        "status": "approved",
        "job_id": job_id
    }

@router.post("/process-done", 
             tags=[ADMIN_TAG, PROCESSING_TAG, EMAIL_TAG])
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

    celery.send_task(
        "tasks.send_job_state_email",
        args=[job_id, "done", "Your audio files are now ready."]
    )

    return {
        "status": "done",
        "job_id": job_id
    }

@router.post("/decline-review",
             tags=[ADMIN_TAG, PROCESSING_TAG, EMAIL_TAG])
def decline_review(
    job_id: str = Form(...),
    reason: str | None = Form(None),
    user=Depends(get_current_user)
):
    # Admin check
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

    update_data = {
        "review_status": "declined",
        "review_declined_at": datetime.utcnow(),
        "review_declined_by": user["_id"]
    }

    # Optional admin feedback
    if reason:
        update_data["review_decline_reason"] = reason

    jobs_collection.update_one(
        {"job_id": job_id},
        {"$set": update_data}
    )

    celery.send_task(
        "tasks.send_job_state_email",
        args=[job_id, "declined", reason]
    )

    return {
        "status": "declined",
        "job_id": job_id,
        "reason": reason
    }

# -------------------------
# ADMIN: List completed audiobooks
# -------------------------
@router.get("/my")
def my_library(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    jobs = jobs_collection.find(
        {"user_id": str(user["_id"]), "is_admin": True, "final_parts": {"$exists": True}},
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
