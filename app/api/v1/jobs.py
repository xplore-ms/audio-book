import uuid

from datetime import datetime, timedelta
from fastapi import (
    APIRouter,
    Query,
    Request,
    UploadFile,
    File,
    HTTPException,
    Depends,
    Form,
)

from app.core.rate_limiter import rate_limit
from app.core.dependencies import get_current_user
from app.domain.credit.service import (
    get_upload_cost,
    add_credits,
    deduct_credits_atomic,
    get_page_cost,
)
from app.utils.config import get_plan_page_limit
from app.integrations.supabase.client import delete_file, upload_bytes
from app.utils.pdf import get_num_pages_and_extension
from app.db.mongo import jobs_collection, job_tasks
from celery import Celery
from celery.result import AsyncResult
from app.core.config import settings
from dotenv import load_dotenv
from pydantic import BaseModel


PLAN_QUICK_COOLDOWNS = {
    "starter": 7200,  # 2 hours
    "professional": 1800,  # 30 minutes
    "mastery": 0,  # Reset after each processing completed
}


class UpdateJobRequest(BaseModel):
    title: str


class ListeningProgressPayload(BaseModel):
    page: int | None = None
    time: float | None = None
    completed: bool | None = None


# -----------------------------
# Utilities for TTS sync
# -----------------------------


load_dotenv()

MAIL_USERNAME = settings.mail.MAIL_USERNAME
MAIL_PASSWORD = settings.mail.MAIL_PASSWORD

router = APIRouter(prefix="", tags=["Jobs"])

celery = Celery("worker")
celery.config_from_object("celeryconfig")


@router.post("/upload")
async def upload_pdf(
    request: Request,
    title: str = Form(...),
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    rate_limit(
        key=f"upload:{user['_id']}:{request.client.host}", limit=3, window_seconds=60
    )
    ext = file.filename.lower().split(".")[-1]
    if ext not in ["pdf", "epub", "txt", "docx"]:
        raise HTTPException(
            400, "Unsupported file format. Allowed: pdf, epub, txt, docx"
        )

    file_bytes = await file.read()

    if ext == "pdf" and not file_bytes.startswith(b"%PDF"):
        raise HTTPException(400, "Invalid PDF file")

    if len(file_bytes) > settings.uploads.MAX_UPLOAD_SIZE:
        raise HTTPException(400, "File too large")

    job_id = str(uuid.uuid4())
    created_at = datetime.utcnow()
    expires_at = created_at + timedelta(days=5)

    folder = f"{created_at.strftime('%Y%m%d')}_{job_id}"
    original_file_name = file.filename

    try:
        pages, storage_ext, processed_bytes = get_num_pages_and_extension(
            file_bytes, original_file_name
        )
    except Exception as e:
        raise HTTPException(400, f"Error processing file: {str(e)}")

    remote_pdf = f"pdfs/{folder}/original{storage_ext}"

    if pages > settings.uploads.MAX_PAGES:
        raise HTTPException(400, "Page limit exceeded")

    deduct_credits_atomic(user["_id"], get_upload_cost())

    try:
        mime_type = "application/pdf"
        if storage_ext == ".epub":
            mime_type = "application/epub+zip"
        elif storage_ext == ".txt":
            mime_type = "text/plain"

        upload_bytes(remote_pdf, processed_bytes, mime_type)
        jobs_collection.insert_one(
            {
                "job_id": job_id,
                "user_id": str(user["_id"]),
                "email": user["email"],
                "title": title,
                "file_name": original_file_name,
                "remote_pdf_path": remote_pdf,
                "folder_name": folder,
                "num_pages": pages,
                "digits": len(str(pages)),
                "extension": storage_ext,
                "created_at": created_at,
                "expires_at": expires_at,
                "status": "uploaded",
            }
        )

    except Exception:
        add_credits(user["_id"], get_upload_cost())
        raise

    return {
        "job_id": job_id,
        "pages": pages,
        "title": title,
        "file_name": original_file_name,
        "expires_at": expires_at,
    }


@router.get("/status/{task_id}")
async def get_task_status(task_id: str):
    res = AsyncResult(task_id, app=celery)
    return {
        "state": res.state,
        "result": res.result if res.state == "SUCCESS" else res.info,
    }


@router.get("/job/{job_id}")
async def get_job(job_id: str, user=Depends(get_current_user)):
    job = jobs_collection.find_one({"job_id": job_id, "user_id": str(user["_id"])})

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    processing_id = job.get("processing_id")

    progress = 100 if job.get("status") == "done" else 0
    task_summary = None

    if job.get("status") == "processing" and processing_id:
        tasks = list(job_tasks.find({"job_id": job_id, "processing_id": processing_id}))
        if tasks:
            succ = sum(1 for t in tasks if t["state"] == "SUCCESS")
            fail = sum(1 for t in tasks if t["state"] == "FAILED")
            proc = sum(1 for t in tasks if t["state"] in ("PENDING", "PROGRESS"))

            total_progress = sum(t.get("progress", 0) for t in tasks)
            progress = round(total_progress / len(tasks))

            task_summary = {
                "completed": succ,
                "failed": fail,
                "processing": proc,
                "total": len(tasks),
            }

    thumbnail_path = job.get("thumbnail_path")
    from app.integrations.supabase.client import _safe_create_signed_url

    thumbnail_url = (
        _safe_create_signed_url(thumbnail_path, 86400) if thumbnail_path else None
    )

    return {
        "job_id": job["job_id"],
        "pages": job["num_pages"],
        "status": job["status"],
        "progress": progress,
        "task_summary": task_summary,
        "title": job["title"],
        "file_name": job["file_name"],
        "created_at": job["created_at"],
        "has_audio": len(job.get("pages", {})) > 0,
        "pages_count": len(job.get("pages", {})),
        "listen_progress": job.get("listen_progress", {}),
        "thumbnail_url": thumbnail_url,
    }


@router.post("/job/{job_id}/reupload")
async def reupload_pdf(
    request: Request,
    job_id: str,
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    rate_limit(
        key=f"upload:{user['_id']}:{request.client.host}", limit=2, window_seconds=60
    )

    # 1. Validate file
    ext = file.filename.lower().split(".")[-1]
    if ext not in ["pdf", "epub", "txt", "docx"]:
        raise HTTPException(
            400, "Unsupported file format. Allowed: pdf, epub, txt, docx"
        )

    file_bytes = await file.read()

    if ext == "pdf" and not file_bytes.startswith(b"%PDF"):
        raise HTTPException(400, "Invalid PDF file")

    if len(file_bytes) > settings.uploads.MAX_UPLOAD_SIZE:
        raise HTTPException(400, "File too large")

    # 2. Find job (ownership check)
    job = jobs_collection.find_one({"job_id": job_id, "user_id": str(user["_id"])})

    if not job:
        raise HTTPException(404, "Job not found")

    # 3. Upload to SAME folder & SAME path logic
    try:
        pages, storage_ext, processed_bytes = get_num_pages_and_extension(
            file_bytes, file.filename
        )
    except Exception as e:
        raise HTTPException(400, f"Error processing file: {str(e)}")

    if pages > settings.uploads.MAX_PAGES:
        raise HTTPException(400, "Page limit exceeded")

    # Validate extension matches the original job (so we replace correct file)
    old_ext = job.get("extension", ".pdf")
    if old_ext != storage_ext:
        raise HTTPException(
            400, f"Must re-upload a file that resolves to the same format ({old_ext})"
        )

    remote_pdf = job["remote_pdf_path"]
    deduct_credits_atomic(user["_id"], get_upload_cost())

    try:
        mime_type = "application/pdf"
        if storage_ext == ".epub":
            mime_type = "application/epub+zip"
        elif storage_ext == ".txt":
            mime_type = "text/plain"

        upload_bytes(remote_pdf, processed_bytes, mime_type)
        jobs_collection.update_one(
            {"job_id": job_id},
            {
                "$set": {
                    "file_name": file.filename,
                    "num_pages": pages,
                    "digits": len(str(pages)),
                    "updated_at": datetime.utcnow(),
                    "reuploaded": True,
                    "status": "uploaded",
                }
            },
        )
    except Exception:
        add_credits(user["_id"], get_upload_cost())
        raise

    # 5. Update job metadata

    return {
        "job_id": job_id,
        "pages": pages,
        "file_name": file.filename,
        "message": "PDF re-uploaded successfully",
    }


@router.patch("/job/{job_id}")
async def update_job(
    job_id: str, payload: UpdateJobRequest, user=Depends(get_current_user)
):
    result = jobs_collection.update_one(
        {"job_id": job_id, "user_id": str(user["_id"])},
        {"$set": {"title": payload.title}},
    )

    if result.matched_count == 0:
        raise HTTPException(404, "Job not found")

    return {"message": "Job updated successfully"}


class ChatPayload(BaseModel):
    message: str
    history: list[dict] = []


@router.get("/job/{job_id}/summary")
async def get_job_summary(job_id: str, user=Depends(get_current_user)):
    job = jobs_collection.find_one({"job_id": job_id, "user_id": str(user["_id"])})
    if not job:
        raise HTTPException(404, "Job not found")

    if job.get("summary"):
        # Check if audio generation is needed and queue it
        if "summary_audio_status" not in job:
            celery.send_task("tasks.generate_summary_audio_task", args=[job_id])
            jobs_collection.update_one(
                {"job_id": job_id}, {"$set": {"summary_audio_status": "processing"}}
            )

        audio_url = job.get("summary_audio_url")
        if not audio_url and job.get("summary_audio_path"):
            from app.integrations.supabase.client import _safe_create_signed_url

            audio_url = _safe_create_signed_url(job.get("summary_audio_path"), 3600)

        return {
            "summary": job["summary"],
            "audio_url": audio_url,
            "audio_status": job.get("summary_audio_status", "pending"),
        }

    from app.integrations.supabase.client import download_to_bytes
    from app.utils.pdf import extract_text_from_bytes
    from app.utils.llm import generate_summary

    remote_path = job.get("remote_pdf_path")
    if not remote_path:
        raise HTTPException(404, "PDF file not found")

    try:
        file_bytes = download_to_bytes(remote_path)
        text = extract_text_from_bytes(file_bytes, job.get("extension", ".pdf"))

        if not text.strip():
            raise ValueError("No extractable text found in the document")

        summary = generate_summary(text)

        # Dispatch TTS for summary
        celery.send_task("tasks.generate_summary_audio_task", args=[job_id])

        jobs_collection.update_one(
            {"job_id": job_id},
            {"$set": {"summary": summary, "summary_audio_status": "processing"}},
        )
        return {"summary": summary, "audio_status": "processing"}
    except Exception as e:
        raise HTTPException(500, f"Error generating summary: {str(e)}")


@router.post("/job/{job_id}/chat")
async def chat_with_job(
    job_id: str, payload: ChatPayload, user=Depends(get_current_user)
):
    job = jobs_collection.find_one({"job_id": job_id, "user_id": str(user["_id"])})
    if not job:
        raise HTTPException(404, "Job not found")

    # We will use the summary as context for the chat if available. We can also fetch the full text,
    # but the full text is not stored in MongoDB and fetching/extracting each time might be too slow.
    # The summary from get_job_summary is an ideal size.
    if not job.get("summary"):
        raise HTTPException(
            400,
            "Summary not yet generated. Please generate the summary first to use chat.",
        )

    from app.utils.llm import chat_with_document

    try:
        reply = chat_with_document(job["summary"], payload.message, payload.history)
        return {"reply": reply}
    except Exception as e:
        raise HTTPException(500, f"Chat error: {str(e)}")


@router.post("/job/{job_id}/listening-progress")
async def update_listening_progress(
    job_id: str, payload: ListeningProgressPayload, user=Depends(get_current_user)
):
    update_data: dict = {}
    if payload.page is not None:
        update_data["listen_progress.page"] = payload.page
    if payload.time is not None:
        update_data["listen_progress.time"] = payload.time
    if payload.completed is not None:
        update_data["listen_progress.completed"] = payload.completed

    if not update_data:
        raise HTTPException(400, "No progress data provided")

    result = jobs_collection.update_one(
        {"job_id": job_id, "user_id": str(user["_id"])}, {"$set": update_data}
    )

    if result.matched_count == 0:
        raise HTTPException(404, "Job not found")

    return {"message": "Progress updated successfully"}


@router.post("/job/{job_id}/start-summary")
def start_summary_job(
    job_id: str,
    voice_id: str | None = None,
    user=Depends(get_current_user),
):
    rate_limit(key=f"summary_start:{user['_id']}", limit=5, window_seconds=3600)

    job = jobs_collection.find_one({"job_id": job_id, "user_id": str(user["_id"])})
    if not job:
        raise HTTPException(404, "Job not found")

    # Resolve Voice
    voice_name = "en-US-Chirp3-HD-Zephyr"
    if voice_id:
        try:
            from app.db.mongo import voices_collection
            from bson.objectid import ObjectId

            v_doc = voices_collection.find_one({"_id": ObjectId(voice_id)})
            if v_doc and "voice_name" in v_doc:
                voice_name = v_doc["voice_name"]
        except Exception:
            pass

    # Flat cost for summary
    SUMMARY_COST = 5
    if user["credits"] < SUMMARY_COST:
        raise HTTPException(
            400, "Insufficient credits for summary (5 credits required)"
        )

    deduct_credits_atomic(user["_id"], SUMMARY_COST)

    try:
        jobs_collection.update_one(
            {"job_id": job_id},
            {
                "$set": {
                    "status": "processing",
                    "mode": "summary",
                    "summary_audio_status": "pending",
                    "started_at": datetime.utcnow(),
                    "voice_name": voice_name,
                }
            },
        )
        celery.send_task("tasks.process_summary", args=[job_id, voice_name])
    except Exception:
        add_credits(user["_id"], SUMMARY_COST)
        raise

    return {"status": "processing", "job_id": job_id}


@router.post("/start")
def start_job(
    job_id: str,
    start: int = 1,
    end: int | None = None,
    voice_id: str | None = None,
    user=Depends(get_current_user),
):
    # Plan-based rate limiting (Cooldowns)
    plan_id = user.get("active_plan_id")

    cooldown = PLAN_QUICK_COOLDOWNS.get(plan_id, 14400)  # Default 4 hours for free
    rate_limit(key=f"quick_start:{user['_id']}", limit=1, window_seconds=cooldown)

    job = jobs_collection.find_one({"job_id": job_id, "user_id": str(user["_id"])})

    if not job:
        raise HTTPException(404, "Document processing not found")

    # Resolve Voice
    voice_name = "en-US-Chirp3-HD-Zephyr"  # Default
    if voice_id:
        try:
            from app.db.mongo import voices_collection
            from bson.objectid import ObjectId

            v_doc = voices_collection.find_one({"_id": ObjectId(voice_id)})
            if v_doc and "voice_name" in v_doc:
                voice_name = v_doc["voice_name"]
        except Exception:
            pass  # Fallback to default if invalid ID

    total = job["num_pages"]
    end = end or total

    if start < 1 or end > total or start > end:
        raise HTTPException(400, "Invalid page range")

    pages = end - start + 1
    if pages > 4:
        raise HTTPException(
            400,
            "Quick processing is limited to 4 pages per run. For full document processing, please use the 'Full Document' mode.",
        )

    total_cost = get_page_cost() * pages
    deduct_credits_atomic(user["_id"], total_cost)
    processing_id = str(uuid.uuid4())
    # Mark job as processing (job-level only)
    jobs_collection.update_one(
        {"job_id": job_id},
        {
            "$set": {
                "status": "processing",
                "processing_id": processing_id,
                "started_at": datetime.utcnow(),
                "voice_name": voice_name,
            }
        },
    )

    try:
        for page in range(start, end + 1):
            res = celery.send_task(
                "tasks.process_page",
                args=[job_id, processing_id, job["remote_pdf_path"], page, voice_name],
            )

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

    except Exception:
        add_credits(user["_id"], total_cost)
        raise

    return {"status": "processing", "pages": pages, "job_id": job_id}


@router.post("/request-full-review")
def request_full_review(
    job_id: str, voice_id: str = Query(None), user=Depends(get_current_user)
):
    job = jobs_collection.find_one({"job_id": job_id, "user_id": str(user["_id"])})
    if not job:
        raise HTTPException(404, "Job not found")

    if job.get("review_required"):
        raise HTTPException(400, "Review already requested")

    # Resolve Voice
    voice_name = job.get("voice_name") or "en-US-AriaNeural"  # Edge fallback
    if voice_id:
        try:
            from app.db.mongo import voices_collection
            from bson.objectid import ObjectId

            v_doc = voices_collection.find_one({"_id": ObjectId(voice_id)})
            if v_doc and "voice_name" in v_doc:
                voice_name = v_doc["voice_name"]
        except Exception:
            pass

    # Enforce Plan Limits
    plan_id = user.get("active_plan_id")
    if not plan_id:
        raise HTTPException(
            403,
            "Full document processing is a premium feature. Please subscribe to a plan to use this.",
        )

    limit = get_plan_page_limit(plan_id)

    if job["num_pages"] > limit:
        raise HTTPException(
            400,
            f"Your current plan ({plan_id}) allows up to {limit} pages for full document processing. "
            f"This document has {job['num_pages']} pages. Please upgrade to a higher plan.",
        )

    try:
        jobs_collection.update_one(
            {"job_id": job_id},
            {
                "$set": {
                    "review_required": True,
                    "review_status": "pending",
                    "requested_at": datetime.utcnow(),
                    "voice_name": voice_name,
                }
            },
        )

        # 🔥 SEND EMAIL ASYNC (NO BLOCKING)
        celery.send_task("tasks.send_review_request_email", args=[job_id])
    except Exception as e:
        # If task dispatch fails, we might want to log it and potentially revert DB state
        # but since the user might try again, let's at least raise a proper error.
        print(f"Failed to queue review request email: {e}")
        # Not raising here because the job is already marked for review, which is the primary state.
        # But maybe we should raise so the user knows it failed?
        # Actually, if the DB update succeeded but email failed, the job IS queued, just admin not notified yet.
        # It's better to keep it marked and maybe retry email later or just log it.
        pass

    return {"status": "queued_for_review", "job_id": job_id}


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


@router.get("/job/{job_id}/progress")
def get_job_progress(job_id: str, user=Depends(get_current_user)):
    job = jobs_collection.find_one({"job_id": job_id, "user_id": str(user["_id"])})

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
            "tasks": tasks,
        }

    # Step 3: Still processing
    return {
        "status": "processing",
        "processing_id": processing_id,
        "progress": calculate_progress(tasks),
        "tasks": tasks,
    }


@router.get("/me/activity")
def my_activity(user=Depends(get_current_user)):
    jobs = jobs_collection.find(
        {"user_id": str(user["_id"])},
        {"_id": 0, "job_id": 1, "num_pages": 1, "created_at": 1, "review_status": 1},
    ).sort("created_at", -1)

    return {"email": user["email"], "credits": user["credits"], "jobs": list(jobs)}


CLEANUP_SECRET_KEY = "my_cron_secret"


@router.post("/cleanup-expired-files")
def cleanup_expired_files(
    key: str = Query(..., description="Secret key to authorize cleanup"),
):
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

    return {"status": "done", "deleted_files": deleted_count, "errors": errors}
