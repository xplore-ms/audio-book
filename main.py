# backend/main.py
from typing import Optional
import uuid
import os
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from celery import Celery
from datetime import datetime

from supabase_client import upload_bytes, download_to_bytes
from pdf_utils import get_num_pages_from_bytes
from mongo import jobs_collection, ensure_indexes

# ensure mongo indexes
ensure_indexes()

app = FastAPI(title="Stateless PDF → Audio Backend")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

celery = Celery("worker")
celery.config_from_object("celeryconfig")


def make_folder_name(job_id: str) -> str:
    date = datetime.utcnow().strftime("%Y%m%d")
    return f"{date}_{job_id}"


@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...), email: str = Form(...)):
    """
    Upload PDF and register job with email (Option A).
    """

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF allowed")

    job_id = str(uuid.uuid4())
    folder_name = make_folder_name(job_id)
    remote_path = f"pdfs/{folder_name}/original.pdf"

    # read bytes from upload
    pdf_bytes = await file.read()
    upload_bytes(remote_path, pdf_bytes, "application/pdf")

    # count pages from bytes
    num_pages = get_num_pages_from_bytes(pdf_bytes)
    # calculate digits for zero-padding, e.g., 100 -> 3
    digits = len(str(num_pages))

    # store metadata in MongoDB
    jobs_collection.insert_one({
        "job_id": job_id,
        "email": email,
        "folder_name": folder_name,
        "remote_pdf_path": remote_path,
        "num_pages": num_pages,
        "digits": digits,
        "created_at": datetime.utcnow()
    })

    return {
        "job_id": job_id,
        "folder_name": folder_name,
        "remote_pdf_path": remote_path,
        "num_pages": num_pages,
        "digits": digits
    }


MAX_PAGES = 4

@app.post("/start-job")
def start_job(job_id: str, remote_pdf_path: str, start: int = 1, end: Optional[int] = None):
    job = jobs_collection.find_one({"job_id": job_id})
    if job is None:
        raise HTTPException(404, "Job not found")

    total = job["num_pages"]
    end = end or total

    # Validate range is inside total pages
    if start < 1 or end > total or start > end:
        raise HTTPException(400, "Invalid page range")

    # Count number of pages requested
    pages_requested = end - start + 1

    # Enforce max of 4 pages
    if pages_requested > MAX_PAGES:
        raise HTTPException(
            400, 
            f"You can only process a maximum of {MAX_PAGES} pages at once. "
            f"You requested {pages_requested} pages."
        )

    # Process pages
    task_ids = []
    for page in range(start, end + 1):
        res = celery.send_task("tasks.process_page", args=[job_id, job["remote_pdf_path"], page])
        task_ids.append(res.id)

    return {
        "job_id": job_id,
        "task_ids": task_ids,
        "pages_processing": pages_requested
    }


@app.get("/status/{task_id}")
def get_status(task_id: str):
    async_result = celery.AsyncResult(task_id)
    return {"state": async_result.state, "result": async_result.result}


@app.post("/merge/{job_id}")
def merge(job_id: str):
    job = jobs_collection.find_one({"job_id": job_id})
    if job is None:
        raise HTTPException(404, "Job not found")

    r = celery.send_task("tasks.merge_pages", args=[job_id])
    return {"merge_task_id": r.id}
