# celeryconfig.py
import os
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

BROKER = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
BACKEND = os.getenv("RESULT_BACKEND", BROKER)

celery_app = Celery("pdf_audio", broker=BROKER, backend=BACKEND)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    result_expires=3600,
    task_soft_time_limit=300,  # default soft limit per-task (can be overridden)
)