from typing import Optional
import uuid
import os
from fastapi import FastAPI, UploadFile, File, HTTPException
from celery import Celery

from supabase_client import upload_bytes, download_to_bytes
from pdf_utils import get_num_pages_from_bytes



app = FastAPI(title="Stateless PDF → Audio Backend")

celery = Celery("worker")
celery.config_from_object("celeryconfig")

@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(400, "Only PDF allowed")

    job_id = str(uuid.uuid4())
    remote_path = f"pdfs/{job_id}/original.pdf"

    pdf_bytes = await file.read()
    upload_bytes(remote_path, pdf_bytes, "application/pdf")

    num_pages = get_num_pages_from_bytes(pdf_bytes)

    return {
        "job_id": job_id,
        "remote_pdf_path": remote_path,
        "num_pages": num_pages
    }

@app.post("/start-job")
def start_job(job_id: str, remote_pdf_path: str, start: int = 1, end: Optional[int] = None):
    pdf_bytes = download_to_bytes(remote_pdf_path)
    total = get_num_pages_from_bytes(pdf_bytes)

    start = start
    end = end or total

    if start < 1 or end > total or start > end:
        raise HTTPException(400, "Invalid page range")

    task_ids = []
    for page in range(start, end + 1):
        r = celery.send_task("tasks.process_page", args=[job_id, remote_pdf_path, page])
        task_ids.append(r.id)

    return {"job_id": job_id, "task_ids": task_ids}

@app.get("/status/{task_id}")
def get_status(task_id: str):
    async_result = celery.AsyncResult(task_id)
    return {"state": async_result.state, "result": async_result.result}


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
def merge(job_id: str):
    r = celery.send_task("tasks.merge_pages", args=[job_id])
    return {"merge_task_id": r.id}
