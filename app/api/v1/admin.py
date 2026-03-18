from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends, Request
from app.db.mongo import (
    jobs_collection,
    users_collection,
    payments_collection,
    job_tasks,
    activities_collection,
    subscriptions_collection,
    app_settings,
)
from app.utils.activity import log_activity
from pydantic import BaseModel, Field

from app.integrations.supabase.client import (
    upload_bytes,
    _safe_create_signed_url,
    _safe_create_download_url,
)
from app.core.security import hash_password, verify_password, create_access_token
from app.utils.pdf import get_num_pages_and_extension
from app.core.dependencies import get_current_user, oauth2_scheme
from celery import Celery
from datetime import datetime, timedelta
import uuid
import time

router = APIRouter(prefix="/admin", tags=["Admin"])

celery = Celery("worker")
celery.config_from_object("celeryconfig")

SUPABASE_ADMIN_FOLDER = "admin_library"
MAX_PAGES_AT_ONCE = 50  # safety limit for batch processing

PLAN_PAGE_LIMITS = {
    "starter": 50,
    "professional": 200,
    "mastery": 5000,  # Effectively unlimited
}
DEFAULT_LIMIT = 5

REVIEW_TAG = "Review Workflow"
PROCESSING_TAG = "Processing"
EMAIL_TAG = "Email Notifications"
ADMIN_TAG = "Admin"


def make_folder_name(job_id: str) -> str:
    return f"{datetime.utcnow().strftime('%Y%m%d')}_{job_id}"


TASK_TIMEOUT = timedelta(hours=1)


def finalize_stuck_tasks(tasks):
    now = datetime.utcnow()
    updated = False
    for task in tasks:
        if task["state"] in ("SUCCESS", "FAILED"):
            continue
        created_at = task.get("created_at")
        if created_at and (now - created_at) > TASK_TIMEOUT:
            job_tasks.update_one(
                {"_id": task["_id"]},
                {
                    "$set": {
                        "state": "FAILED",
                        "progress": 100,
                        "error": "Task timed out",
                        "updated_at": now,
                    }
                },
            )
            task["state"] = "FAILED"
            task["progress"] = 100
            updated = True
    return updated


def all_tasks_terminal(tasks):
    return all(t["state"] in ("SUCCESS", "FAILED") for t in tasks)


def calculate_progress(tasks):
    if not tasks:
        return 0
    return round(sum(t.get("progress", 0) for t in tasks) / len(tasks))


# -------------------------
# ADMIN: Upload PDF + specify credits
# -------------------------
@router.post("/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    title: str = Form(...),
    category: str = Form(...),
    required_credits: int = Form(1),
    user=Depends(get_current_user),
):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    ext = file.filename.lower().split(".")[-1]
    if ext not in ["pdf", "epub", "txt", "docx"]:
        raise HTTPException(
            400, "Unsupported file format. Allowed: pdf, epub, txt, docx"
        )

    file_bytes = await file.read()
    job_id = str(uuid.uuid4())
    folder_name = make_folder_name(job_id)

    original_file_name = file.filename

    try:
        pages, storage_ext, processed_bytes = get_num_pages_and_extension(
            file_bytes, original_file_name
        )
    except Exception as e:
        raise HTTPException(400, f"Error processing file: {str(e)}")

    remote_path = f"{SUPABASE_ADMIN_FOLDER}/pdfs/{folder_name}/original{storage_ext}"

    mime_type = "application/pdf"
    if storage_ext == ".epub":
        mime_type = "application/epub+zip"
    elif storage_ext == ".txt":
        mime_type = "text/plain"

    upload_bytes(remote_path, processed_bytes, mime_type)

    # Count pages
    num_pages = pages
    digits = len(str(num_pages))

    # Save metadata
    jobs_collection.insert_one(
        {
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
            "extension": storage_ext,
            "required_credits": required_credits,  # credits required to listen
            "sync": {},
            "created_at": datetime.utcnow(),
        }
    )

    log_activity(
        user_id=str(user["_id"]),
        activity_type="admin_upload",
        description=f"Admin uploaded file: {original_file_name}",
        is_admin_action=True,
        metadata={"job_id": job_id, "title": title, "category": category},
    )

    return {
        "job_id": job_id,
        "folder_name": folder_name,
        "remote_pdf_path": remote_path,
        "num_pages": num_pages,
        "digits": digits,
        "required_credits": required_credits,
    }


@router.post("/start-admin-job")
def start_job(
    job_id: str, start: int = 1, end: int | None = None, user=Depends(get_current_user)
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

    processing_id = str(uuid.uuid4())

    # Mark job as processing
    jobs_collection.update_one(
        {"job_id": job_id},
        {
            "$set": {
                "status": "processing",
                "processing_id": processing_id,
                "started_at": datetime.utcnow(),
            }
        },
    )

    task_ids = []
    for page in range(start, end + 1):
        res = celery.send_task(
            "tasks.process_admin_page",
            args=[
                job_id,
                job["remote_pdf_path"],
                page,
                processing_id,
                job.get("voice_name", "en-US-AriaNeural"),
            ],
        )
        task_ids.append(res.id)

        # Initialize tracking record
        job_tasks.insert_one(
            {
                "job_id": job_id,
                "page": page,
                "processing_id": processing_id,
                "state": "PENDING",
                "progress": 0,
                "celery_task_id": res.id,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        )

    return {
        "status": "processing",
        "pages": pages,
        "job_id": job_id,
        "processing_id": processing_id,
        "task_ids": task_ids,
        "total_pages": total,
    }


@router.get("/metrics/overview")
def admin_metrics_overview(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")

    total_users = users_collection.count_documents({})
    total_jobs = jobs_collection.count_documents({})

    users_with_credits = users_collection.count_documents({"credits": {"$gt": 0}})

    review_pending = jobs_collection.count_documents({"review_status": "pending"})

    review_done = jobs_collection.count_documents({"review_status": "done"})

    return {
        "users": {"total": total_users, "with_credits": users_with_credits},
        "jobs": {
            "total": total_jobs,
            "review_pending": review_pending,
            "review_done": review_done,
        },
    }


@router.get("/metrics/users")
def admin_user_metrics(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")

    now = datetime.utcnow()

    last_7_days = users_collection.count_documents(
        {"created_at": {"$gte": now - timedelta(days=7)}}
    )

    last_30_days = users_collection.count_documents(
        {"created_at": {"$gte": now - timedelta(days=30)}}
    )

    total_credits = list(
        users_collection.aggregate(
            [{"$group": {"_id": None, "total": {"$sum": "$credits"}}}]
        )
    )

    total_credits = total_credits[0]["total"] if total_credits else 0

    return {
        "new_users": {"last_7_days": last_7_days, "last_30_days": last_30_days},
        "credits": {"total_remaining": total_credits},
    }


@router.get("/metrics/revenue")
def admin_revenue_metrics(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")

    pipeline = [
        {"$match": {"status": "success"}},
        {
            "$group": {
                "_id": {
                    "year": {"$year": "$verified_at"},
                    "month": {"$month": "$verified_at"},
                    "day": {"$dayOfMonth": "$verified_at"},
                },
                "total_revenue_kobo": {"$sum": "$amount"},
                "count": {"$sum": 1},
            }
        },
        {"$sort": {"_id.year": -1, "_id.month": -1, "_id.day": -1}},
        {"$limit": 30},
    ]

    daily_revenue = list(payments_collection.aggregate(pipeline))

    # Total revenue
    total_pipeline = [
        {"$match": {"status": "success"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ]
    total_res = list(payments_collection.aggregate(total_pipeline))
    total_revenue_kobo = total_res[0]["total"] if total_res else 0

    return {
        "total_revenue_ngn": total_revenue_kobo / 100,
        "daily_revenue": [
            {
                "date": f"{r['_id']['year']}-{r['_id']['month']:02d}-{r['_id']['day']:02d}",
                "amount_ngn": r["total_revenue_kobo"] / 100,
                "transaction_count": r["count"],
            }
            for r in daily_revenue
        ],
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
                "pages": {"$sum": "$num_pages"},
            }
        },
        {"$sort": {"jobs_created": -1}},
        {"$limit": 10},
    ]

    top_users = list(jobs_collection.aggregate(pipeline))

    return {
        "top_active_users": [
            {
                "user_id": str(u["_id"]),
                "jobs_created": u["jobs_created"],
                "pages_processed": u["pages"],
            }
            for u in top_users
        ]
    }


# -------------------------
# ADMIN: Start processing PDF → audio
# -------------------------
@router.post("/process-job", tags=[ADMIN_TAG, PROCESSING_TAG, EMAIL_TAG])
def start_admin_request_job(
    job_id: str = Form(...),
    start: int = Form(1),
    end: int = Form(None),
    user=Depends(get_current_user),
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
            status_code=403, detail="Job requires admin approval before processing"
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
            f"Max allowed per batch: {MAX_PAGES_AT_ONCE}",
        )

    # Trigger Celery tasks for each page
    processing_id = str(uuid.uuid4())

    # Mark job as processing
    jobs_collection.update_one(
        {"job_id": job_id},
        {
            "$set": {
                "status": "processing",
                "processing_id": processing_id,
                "started_at": datetime.utcnow(),
            }
        },
    )

    task_ids = []
    voice_name = job.get("voice_name", "en-US-AriaNeural")
    for page in range(start, end + 1):
        task = celery.send_task(
            "tasks.process_page",
            args=[job_id, processing_id, job["remote_pdf_path"], page, voice_name],
        )
        task_ids.append(task.id)

        # Initialize tracking record
        job_tasks.insert_one(
            {
                "job_id": job_id,
                "page": page,
                "processing_id": processing_id,
                "state": "PENDING",
                "progress": 0,
                "celery_task_id": task.id,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        )

    celery.send_task(
        "tasks.send_job_state_email",
        args=[job_id, "processing", "Your job has started processing."],
    )

    log_activity(
        user_id=str(user["_id"]),
        activity_type="admin_job_start",
        description=f"Admin started processing job {job_id}",
        is_admin_action=True,
        metadata={"job_id": job_id, "pages": pages_requested},
    )

    return {
        "job_id": job_id,
        "processing_id": processing_id,
        "task_ids": task_ids,
        "pages_processing": pages_requested,
        "total_pages": total_pages,
    }


@router.get("/job/{job_id}/progress")
def get_admin_job_progress(job_id: str, user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")

    job = jobs_collection.find_one({"job_id": job_id})
    if not job:
        raise HTTPException(404, "Job not found")

    processing_id = job.get("processing_id")
    if not processing_id:
        return {"status": "processing", "progress": 0}

    tasks = list(job_tasks.find({"job_id": job_id, "processing_id": processing_id}))

    # Step 1: Finalize stuck tasks
    finalize_stuck_tasks(tasks)

    for task in tasks:
        task["_id"] = str(task["_id"])

    # Step 2: Decide job completion
    job_created_at = job.get("created_at")
    job_timed_out = job_created_at and (datetime.utcnow() - job_created_at) > timedelta(
        hours=1
    )

    mapped_tasks = [
        {
            "id": t["celery_task_id"],
            "page": t["page"],
            "status": t["state"],
            "percent": t.get("progress", 0),
        }
        for t in tasks
    ]

    if all_tasks_terminal(tasks) or job_timed_out:
        if job.get("status") != "done":
            jobs_collection.update_one(
                {"job_id": job_id},
                {"$set": {"status": "done", "completed_at": datetime.utcnow()}},
            )

        return {
            "status": "done",
            "processing_id": processing_id,
            "progress": 100,
            "tasks": mapped_tasks,
        }

    # Step 3: Still processing
    return {
        "status": "processing",
        "processing_id": processing_id,
        "progress": calculate_progress(tasks),
        "tasks": mapped_tasks,
    }


@router.post("/approve-review", tags=[ADMIN_TAG, REVIEW_TAG, EMAIL_TAG])
def approve_review(job_id: str = Form(...), user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    job = jobs_collection.find_one(
        {"job_id": job_id, "review_required": True, "review_status": "pending"}
    )

    if not job:
        raise HTTPException(status_code=404, detail="Pending review job not found")

    from bson import ObjectId

    request_user_ref = users_collection.find_one({"_id": ObjectId(job["user_id"])})
    if not request_user_ref:
        raise HTTPException(status_code=404, detail="Requesting user not found")

    # Job is governed by plan limits checked during request, no credit deduction here
    jobs_collection.update_one(
        {"job_id": job_id},
        {
            "$set": {
                "review_status": "approved",
                "review_approved_at": datetime.utcnow(),
                "review_approved_by": user["_id"],
            }
        },
    )

    celery.send_task("tasks.send_job_state_email", args=[job_id, "approved", None])

    log_activity(
        user_id=str(user["_id"]),
        activity_type="review_approved",
        description=f"Admin approved review for job {job_id}",
        is_admin_action=True,
        metadata={"job_id": job_id, "owner_email": request_user_ref["email"]},
    )

    return {"status": "approved", "job_id": job_id}


@router.post("/process-done", tags=[ADMIN_TAG, PROCESSING_TAG, EMAIL_TAG])
def done_processing(job_id: str = Form(...), user=Depends(get_current_user)):
    # Admin only
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    job = jobs_collection.find_one({"job_id": job_id, "review_required": True})

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.get("review_status") != "approved":
        raise HTTPException(status_code=400, detail="Job is not in approved state")

    jobs_collection.update_one(
        {"job_id": job_id},
        {
            "$set": {
                "review_status": "done",
                "review_done_at": datetime.utcnow(),
                "review_done_by": user["_id"],
            }
        },
    )

    celery.send_task(
        "tasks.send_job_state_email",
        args=[job_id, "done", "Your audio files are now ready."],
    )

    log_activity(
        user_id=str(user["_id"]),
        activity_type="review_done",
        description=f"Admin marked job {job_id} as done",
        is_admin_action=True,
        metadata={"job_id": job_id},
    )

    return {"status": "done", "job_id": job_id}


@router.post("/revert-review", tags=[ADMIN_TAG, REVIEW_TAG])
def revert_review(job_id: str = Form(...), user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    job = jobs_collection.find_one({"job_id": job_id, "review_status": "done"})
    if not job:
        raise HTTPException(
            status_code=404, detail="Job not found or not in 'done' status"
        )

    jobs_collection.update_one(
        {"job_id": job_id},
        {
            "$set": {
                "review_status": "approved",
                "reverted_at": datetime.utcnow(),
                "reverted_by": user["_id"],
            }
        },
    )

    log_activity(
        user_id=str(user["_id"]),
        activity_type="review_reverted",
        description=f"Admin reverted job {job_id} from done to approved",
        is_admin_action=True,
        metadata={"job_id": job_id},
    )

    return {"status": "approved", "job_id": job_id}


@router.post("/decline-review", tags=[ADMIN_TAG, PROCESSING_TAG, EMAIL_TAG])
def decline_review(
    job_id: str = Form(...),
    reason: str | None = Form(None),
    user=Depends(get_current_user),
):
    # Admin check
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    job = jobs_collection.find_one(
        {"job_id": job_id, "review_required": True, "review_status": "pending"}
    )

    if not job:
        raise HTTPException(status_code=404, detail="Pending review job not found")

    update_data = {
        "review_status": "declined",
        "review_declined_at": datetime.utcnow(),
        "review_declined_by": user["_id"],
    }

    # Optional admin feedback
    if reason:
        update_data["review_decline_reason"] = reason

    jobs_collection.update_one({"job_id": job_id}, {"$set": update_data})

    celery.send_task("tasks.send_job_state_email", args=[job_id, "declined", reason])

    return {"status": "declined", "job_id": job_id, "reason": reason}

    log_activity(
        user_id=str(user["_id"]),
        activity_type="review_declined",
        description=f"Admin declined review for job {job_id}",
        is_admin_action=True,
        metadata={"job_id": job_id, "reason": reason},
    )


# -------------------------
# ADMIN: List completed audiobooks
# -------------------------
@router.get("/my")
def my_library(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    jobs = jobs_collection.find(
        {
            "user_id": str(user["_id"]),
            "is_admin": True,
            "final_parts": {"$exists": True},
        },
        {
            "_id": 0,
            "job_id": 1,
            "final_parts": 1,
            "final_size_mb": 1,
            "required_credits": 1,
        },
    )
    return list(jobs)


@router.get("/reviews")
def list_review_requests(
    search: str | None = None,
    status: str | None = None,
    page: int = 1,
    limit: int = 10,
    user=Depends(get_current_user),
):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    match_stage = {
        "review_required": True,
        "is_admin": {"$ne": True},
    }

    if status and status != "all":
        match_stage["review_status"] = status
    else:
        match_stage["review_status"] = {"$in": ["pending", "approved", "done"]}

    if search:
        match_stage["$or"] = [
            {"title": {"$regex": search, "$options": "i"}},
            {"job_id": {"$regex": search, "$options": "i"}},
        ]

    pipeline = [
        {"$match": match_stage},
        {"$addFields": {"user_id_obj": {"$toObjectId": "$user_id"}}},
        {
            "$lookup": {
                "from": "users",
                "localField": "user_id_obj",
                "foreignField": "_id",
                "as": "user",
            }
        },
        {"$unwind": "$user"},
    ]

    # If search is email, we might need to filter after lookup or add user email to match
    # Let's add email search to match stage using a separate filter if needed,
    # but for now let's keep it simple or use a joined filter.
    if search:
        pipeline.append(
            {
                "$match": {
                    "$or": [
                        {"title": {"$regex": search, "$options": "i"}},
                        {"job_id": {"$regex": search, "$options": "i"}},
                        {"user.email": {"$regex": search, "$options": "i"}},
                    ]
                }
            }
        )

    # Calculate total for pagination
    count_pipeline = pipeline + [{"$count": "total"}]
    total_res = list(jobs_collection.aggregate(count_pipeline))
    total = total_res[0]["total"] if total_res else 0

    pipeline.extend(
        [
            {
                "$project": {
                    "_id": 0,
                    "job_id": 1,
                    "title": 1,
                    "num_pages": 1,
                    "requested_at": 1,
                    "review_status": 1,
                    "user_id": 1,
                    "voice_name": 1,
                    "user_email": "$user.email",
                    "user_credits": "$user.credits",
                }
            },
            {"$sort": {"requested_at": -1}},
            {"$skip": (page - 1) * limit},
            {"$limit": limit},
        ]
    )

    return {
        "reviews": list(jobs_collection.aggregate(pipeline)),
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit,
    }


@router.get("/users")
def list_system_users(
    search: str | None = None, status: str | None = None, user=Depends(get_current_user)
):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")

    query = {}
    if search:
        query["email"] = {"$regex": search, "$options": "i"}

    if status == "verified":
        query["email_verified"] = True
    elif status == "pending":
        query["email_verified"] = {"$ne": True}
    elif status == "suspended":
        query["is_suspended"] = True

    users = users_collection.find(query, {"password_hash": 0}).sort("created_at", -1)
    return [
        {
            **u,
            "_id": str(u["_id"]),
            "id": str(u["_id"]),
            "email_verified": u.get("email_verified", False),
            "active_plan_id": u.get("active_plan_id", "free"),
            "is_suspended": u.get("is_suspended", False),
        }
        for u in users
    ]


@router.post("/users/verify-email")
def admin_verify_user_email(user_id: str = Form(...), user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")

    from bson import ObjectId

    users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"email_verified": True, "email_verified_at": datetime.utcnow()}},
    )

    target_user = users_collection.find_one({"_id": ObjectId(user_id)})
    log_activity(
        user_id=user_id,
        activity_type="email_verified",
        description=f"Email verified by admin {user['email']}",
        is_admin_action=True,
        metadata={"admin_email": user["email"]},
    )

    return {"message": f"Email verified for {target_user['email']}"}


@router.post("/users/change-plan")
def admin_change_user_plan(
    user_id: str = Form(...), plan_id: str = Form(...), user=Depends(get_current_user)
):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")

    from bson import ObjectId

    users_collection.update_one(
        {"_id": ObjectId(user_id)}, {"$set": {"active_plan_id": plan_id}}
    )

    # Also update/create subscription record if needed
    subscriptions_collection.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "plan_id": plan_id,
                "status": "active",
                "updated_at": datetime.utcnow(),
            }
        },
        upsert=True,
    )

    target_user = users_collection.find_one({"_id": ObjectId(user_id)})
    log_activity(
        user_id=user_id,
        activity_type="plan_change",
        description=f"Plan changed to {plan_id} by admin {user['email']}",
        is_admin_action=True,
        metadata={"admin_email": user["email"], "new_plan": plan_id},
    )

    return {"message": f"Plan updated to {plan_id} for {target_user['email']}"}


@router.post("/users/toggle-suspension")
def admin_toggle_user_suspension(
    user_id: str = Form(...), user=Depends(get_current_user)
):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")

    from bson import ObjectId

    target = users_collection.find_one({"_id": ObjectId(user_id)})
    if not target:
        raise HTTPException(404, "User not found")

    new_status = not target.get("is_suspended", False)
    users_collection.update_one(
        {"_id": ObjectId(user_id)}, {"$set": {"is_suspended": new_status}}
    )

    log_activity(
        user_id=user_id,
        activity_type="suspension_toggle",
        description=f"User {'suspended' if new_status else 'unsuspended'} by admin {user['email']}",
        is_admin_action=True,
        metadata={"admin_email": user["email"], "suspended": new_status},
    )

    return {
        "message": f"User {'suspended' if new_status else 'unsuspended'} successfully"
    }


@router.get("/activities")
def list_activities(
    limit: int = 50,
    type: str | None = None,
    user_id: str | None = None,
    user=Depends(get_current_user),
):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")

    query = {}
    if type:
        query["activity_type"] = type
    if user_id:
        query["user_id"] = user_id

    activities = list(
        activities_collection.find(query).sort("created_at", -1).limit(limit)
    )
    return [{**a, "_id": str(a["_id"])} for a in activities]


@router.get("/users/{user_id}/activities")
def list_user_activities(user_id: str, user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")

    activities = list(
        activities_collection.find({"user_id": user_id}).sort("created_at", -1)
    )
    return [{**a, "_id": str(a["_id"])} for a in activities]


@router.post("/users/credits")
def adjust_user_credits(
    user_id: str = Form(...), amount: int = Form(...), user=Depends(get_current_user)
):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")

    from app.domain.credit.service import add_credits
    from bson import ObjectId

    try:
        from bson import ObjectId

        add_credits(ObjectId(user_id), amount)

        log_activity(
            user_id=user_id,
            activity_type="credit_adjustment",
            description=f"Credits adjusted by {amount} by admin {user['email']}",
            is_admin_action=True,
            metadata={"admin_email": user["email"], "amount": amount},
        )
        return {"message": f"Successfully adjusted credits by {amount}"}
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/retry-task")
def retry_task(
    job_id: str = Form(...),
    processing_id: str = Form(...),
    page: int = Form(...),
    user=Depends(get_current_user),
):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")

    job = jobs_collection.find_one({"job_id": job_id})
    if not job:
        raise HTTPException(404, "Job not found")

    # Reset task state in DB
    job_tasks.update_one(
        {"job_id": job_id, "processing_id": processing_id, "page": page},
        {
            "$set": {
                "state": "PENDING",
                "progress": 0,
                "error": None,
                "updated_at": datetime.utcnow(),
            }
        },
    )

    # Determine which task to trigger
    task_name = "tasks.process_page"
    args = [job_id, processing_id, job["remote_pdf_path"], page]

    if job.get("is_admin"):
        # Admin jobs use a different task or same task with different logic?
        # Based on routes, start-admin-job uses tasks.process_admin_page
        task_name = "tasks.process_admin_page"
        args = [job_id, job["remote_pdf_path"], page, processing_id]

    task = celery.send_task(task_name, args=args)

    # Update celery_task_id
    job_tasks.update_one(
        {"job_id": job_id, "processing_id": processing_id, "page": page},
        {"$set": {"celery_task_id": task.id}},
    )

    return {"message": "Task retried", "task_id": task.id}


@router.post("/create-admin")
def create_admin_user(
    email: str = Form(...), password: str = Form(...), user=Depends(get_current_user)
):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    if users_collection.find_one({"email": email}):
        raise HTTPException(400, "Email already exists")

    users_collection.insert_one(
        {
            "email": email,
            "password_hash": hash_password(password),
            "credits": 0,
            "role": "admin",
            "created_at": datetime.utcnow(),
        }
    )

    log_activity(
        user_id=str(user["_id"]),
        activity_type="admin_created",
        description=f"New admin user created: {email}",
        is_admin_action=True,
        metadata={"new_admin": email},
    )

    return {"message": "Admin user created successfully"}


@router.post("/login")
def admin_login(email: str = Form(...), password: str = Form(...)):
    admin = users_collection.find_one({"email": email, "role": "admin"})

    if not admin:
        raise HTTPException(status_code=401, detail="Invalid admin credentials")

    if not verify_password(password, admin["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid admin credentials")

    token = create_access_token(email)

    return {"access_token": token, "token_type": "bearer", "role": "admin"}


@router.get("/users/{user_id}/audios")
def list_user_audios(user_id: str, user=Depends(get_current_user)):
    """
    List all audios/jobs for a specific user. Admin only.
    """
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    jobs_cursor = jobs_collection.find(
        {"user_id": user_id},
        {
            "_id": 0,
            "job_id": 1,
            "title": 1,
            "file_name": 1,
            "created_at": 1,
            "status": 1,
            "num_pages": 1,
        },
    ).sort("created_at", -1)

    return list(jobs_cursor)


@router.get("/users/{user_id}/audios/{job_id}/pages")
def get_user_audio_pages(
    user_id: str,
    job_id: str,
    request: Request,
    skip: int = 0,
    limit: int = 5,
    user=Depends(get_current_user),
    token: str = Depends(oauth2_scheme),
):
    """
    Get signed URLs for a user's audiobook pages. Admin only.
    """
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    job = jobs_collection.find_one({"job_id": job_id, "user_id": user_id})
    if not job or "pages" not in job:
        raise HTTPException(404, "Pages not found for this user job")

    pages = job.get("pages", {})
    # Sort keys
    try:
        ordered_keys = sorted(pages.keys(), key=lambda k: int(k.split("_")[-1]))
    except (ValueError, IndexError):
        ordered_keys = sorted(pages.keys())

    # Paginate
    paged_keys = ordered_keys[skip : skip + limit]

    playlist = []
    now = int(time.time())
    expires_at = now + 900  # 15 minutes TTL

    for key in paged_keys:
        page = pages[key]
        audio_path = page.get("audio_path")
        hls_path = page.get("hls_path")
        final_path = audio_path or hls_path

        if not final_path:
            continue

        if audio_path:
            audio_url = _safe_create_signed_url(audio_path, 900)
        elif hls_path:
            base_url = str(request.base_url).rstrip("/")
            if (
                "localhost" not in base_url
                and "127.0.0.1" not in base_url
                and base_url.startswith("http://")
            ):
                base_url = base_url.replace("http://", "https://", 1)
            audio_url = f"{base_url}/api/v1/audio/hls/{job_id}/{key}/playlist.m3u8?token={token}"
        else:
            continue

        download_url = None
        if audio_path:
            download_url = _safe_create_download_url(
                audio_path, 900, filename=f"{job.get('title', 'audio')}_{key}.mp3"
            )

        sync_url = (
            _safe_create_signed_url(page["sync_path"], 900)
            if page.get("sync_path")
            else None
        )

        playlist.append(
            {
                "page": key,
                "audio_url": audio_url,
                "download_url": download_url,
                "sync_url": sync_url,
                "duration": page.get("duration", 0),
                "expires_at": expires_at,
            }
        )

    return {
        "job_id": job.get("job_id"),
        "title": job.get("title"),
        "pages": playlist,
        "total_pages": len(ordered_keys),
        "skip": skip,
        "limit": limit,
    }


# -------------------------
# ADMIN: Settings & Plans
# -------------------------


class GlobalConfigUpdate(BaseModel):
    upload_cost: int | None = Field(default=None, ge=0)
    page_cost: int | None = Field(default=None, ge=0)
    default_limit: int | None = Field(default=None, ge=0)
    base_price_kobo: int | None = Field(default=None, ge=0)


class PlanUpdate(BaseModel):
    credits: int = Field(ge=0)
    price_ngn: int = Field(ge=0)
    page_limit: int = Field(ge=0)


@router.get("/config", tags=[ADMIN_TAG])
def get_global_config(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")

    config = app_settings.find_one({"type": "global_config"})
    if not config:
        # Defaults based on current hardcoded values
        return {
            "upload_cost": 10,
            "page_cost": 1,
            "default_limit": 5,
            "base_price_kobo": 5000,
        }
    config.pop("_id", None)
    config.pop("type", None)
    return config


@router.patch("/config", tags=[ADMIN_TAG])
def update_global_config(payload: GlobalConfigUpdate, user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")

    update_data = {k: v for k, v in payload.dict().items() if v is not None}
    if not update_data:
        return {"message": "No changes"}

    app_settings.update_one(
        {"type": "global_config"}, {"$set": update_data}, upsert=True
    )

    log_activity(
        user_id=str(user["_id"]),
        activity_type="update_config",
        description="Admin updated global system configuration",
        is_admin_action=True,
        metadata=update_data,
    )

    return {"message": "Config updated", "updated": update_data}


@router.get("/plans", tags=[ADMIN_TAG])
def get_plans(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")

    plans_cursor = app_settings.find({"type": "plan"})
    plans = list(plans_cursor)

    if not plans:
        # Defaults based on current hardcoded values
        return [
            {"plan_id": "starter", "credits": 50, "price_ngn": 1000, "page_limit": 50},
            {
                "plan_id": "professional",
                "credits": 120,
                "price_ngn": 2000,
                "page_limit": 200,
            },
            {
                "plan_id": "mastery",
                "credits": 500,
                "price_ngn": 5000,
                "page_limit": 5000,
            },
        ]

    for p in plans:
        p.pop("_id", None)
        p.pop("type", None)

    return plans


@router.put("/plans/{plan_id}", tags=[ADMIN_TAG])
def update_plan(plan_id: str, payload: PlanUpdate, user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")

    plan_data = payload.dict()
    plan_data["plan_id"] = plan_id
    plan_data["type"] = "plan"

    app_settings.update_one(
        {"type": "plan", "plan_id": plan_id}, {"$set": plan_data}, upsert=True
    )

    log_activity(
        user_id=str(user["_id"]),
        activity_type="update_plan",
        description=f"Admin updated plan: {plan_id}",
        is_admin_action=True,
        metadata=plan_data,
    )

    return {"message": f"Plan {plan_id} updated", "plan": plan_data}
