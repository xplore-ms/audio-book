# tasks.py
import os
import logging
from pydub import AudioSegment

from celeryconfig import celery_app
from pdf_utils import extract_page_text
from genai_helper import clean_text_with_gemini
from tts import generate_speech
from storage import (
    upload_file_to_supabase,
    download_file_from_supabase,
    cleanup_folder,
)

logger = logging.getLogger(__name__)

TEMP_BASE = "temp/jobs"   # <------ Option A folder base


@celery_app.task(bind=True, name="process_page_task", max_retries=2)
def process_page_task(self, job_id: str, page_number: int):
    try:
        job_dir = os.path.join(TEMP_BASE, job_id)
        local_pdf = os.path.join(job_dir, "original.pdf")

        # PDF must exist locally
        if not os.path.exists(local_pdf):
            raise FileNotFoundError(f"Missing local PDF: {local_pdf}")

        # Extract + clean
        text = extract_page_text(local_pdf, page_number - 1)
        cleaned = clean_text_with_gemini(text)

        # Generate MP3 path
        local_mp3 = os.path.join(job_dir, f"page_{page_number}.mp3")

        # Generate TTS
        generate_speech(cleaned, local_mp3)

        # Upload MP3 to Supabase
        remote_mp3 = f"pdfs/{job_id}/audio/page_{page_number}.mp3"
        url = upload_file_to_supabase(local_mp3, remote_mp3, "audio/mpeg")
        # DELETE local mp3 after successful upload
        if os.path.exists(local_mp3):
            os.remove(local_mp3)

        return {"page": page_number, "mp3_url": url}

    except Exception as exc:
        raise self.retry(exc=exc, countdown=5)


@celery_app.task()
def merge_job_mp3s(job_id: str):
    job_dir = os.path.join(TEMP_BASE, job_id)
    from .storage import supabase, SUPABASE_BUCKET

    # List MP3 files from Supabase
    path_to_audio = f"pdfs/{job_id}/audio/"
    files = supabase.storage.from_(SUPABASE_BUCKET).list(path_to_audio)
    mp3_names = sorted([f["name"] for f in files if f["name"].endswith(".mp3")])

    print(mp3_names, "to merge")
    local_paths = []
    for name in mp3_names:
        lp = os.path.join(job_dir, name)
        download_file_from_supabase(f"pdfs/{job_id}/audio/{name}", lp)
        local_paths.append(lp)

    # Merge audio
    merged = AudioSegment.empty()
    for lp in local_paths:
        merged += AudioSegment.from_mp3(lp)

    final_local = os.path.join(job_dir, f"{job_id}_final.mp3")
    merged.export(final_local, format="mp3")

    # Upload final
    remote = f"{job_id}/{job_id}_final.mp3"
    final_url = upload_file_to_supabase(final_local, remote, "audio/mpeg")

    if os.path.exists(final_local):
        os.remove(final_local)


    # Cleanup entire job folder
    cleanup_folder(job_dir)

    return {"job_id": job_id, "final_url": final_url}
