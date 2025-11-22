# main.py
import os
import uuid
from fastapi import FastAPI, UploadFile, File, HTTPException
from dotenv import load_dotenv
from typing import Optional

from storage import upload_raw_file_to_supabase, download_file_from_supabase
from pdf_utils import get_num_pages
from tasks import process_page_task, merge_job_mp3s

load_dotenv()

TEMP_BASE = "temp/jobs"   # <------ OPTION A

app = FastAPI(title="PDF → Audio Service")


@app.post("/upload")
async def upload_pdf_backend(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files allowed")

    job_id = str(uuid.uuid4())
    remote_path = f"pdfs/{job_id}/{file.filename}"

    # Upload raw stream directly to Supabase
    url = upload_raw_file_to_supabase(
        file.file,
        remote_path,
        content_type="application/pdf",
    )

    # Prepare job temp folder
    job_dir = os.path.join(TEMP_BASE, job_id)
    os.makedirs(job_dir, exist_ok=True)

    # Local copy for page counting
    local_pdf = os.path.join(job_dir, "original.pdf")
    download_file_from_supabase(remote_path, local_pdf)

    num_pages = get_num_pages(local_pdf)

    return {
        "job_id": job_id,
        "remote_pdf_path": remote_path,
        "pdf_url": url,
        "num_pages": num_pages,
    }


@app.post("/start-job")
async def start_job(job_id: str, remote_pdf_path: str, start: int = 1, end: Optional[int] = None):
    job_dir = os.path.join(TEMP_BASE, job_id)
    local_pdf = os.path.join(job_dir, "original.pdf")

    # ensure PDF exists locally
    if not os.path.exists(local_pdf):
        download_file_from_supabase(remote_pdf_path, local_pdf)

    total_pages = get_num_pages(local_pdf)

    if end is None:
        end = total_pages

    if start < 1 or end > total_pages or start > end:
        raise HTTPException(400, "Invalid page range")

    task_ids = []
    for page in range(start, end + 1):
        res = process_page_task.delay(job_id, page)  # <---- FIX: only pass job_id + page
        task_ids.append(res.id)

    return {
        "job_id": job_id,
        "pages": [start, end],
        "task_ids": task_ids,
    }


@app.get("/status/{task_id}")
async def task_status(task_id: str):
    ar = process_page_task.AsyncResult(task_id)
    info = {"id": task_id, "state": ar.state}

    if ar.state == "SUCCESS":
        info["result"] = ar.result
    elif ar.state == "FAILURE":
        info["result"] = str(ar.result)

    return info


@app.post("/merge/{job_id}")
async def merge_job(job_id: str):
    res = merge_job_mp3s.delay(job_id)
    return {"merge_task_id": res.id}
