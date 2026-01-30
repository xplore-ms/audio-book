# mongo.py
import os
from dotenv import load_dotenv
load_dotenv()

from pymongo import MongoClient, ASCENDING, DESCENDING
from datetime import datetime

MONGO_URL = os.getenv("MONGO_URL")
MONGO_DB = os.getenv("MONGO_DB", "pdf_audio")

client = MongoClient(MONGO_URL)
db = client[MONGO_DB]
# -------------------
# Collections
# -------------------
jobs_collection = db["jobs"]
job_tasks = db["job_tasks"]          # ✅ TASK-LEVEL PROGRESS
users_collection = db["users"]
payments_collection = db["payments"]


def ensure_indexes():
    # ===================
    # Jobs
    # ===================
    jobs_collection.create_index(
        [("job_id", ASCENDING)],
        unique=True
    )

    jobs_collection.create_index(
        [("user_id", ASCENDING)]
    )

    jobs_collection.create_index(
        [("status", ASCENDING)]
    )

    jobs_collection.create_index(
        [("created_at", DESCENDING)]
    )

    # ===================
    # Job Tasks (CRITICAL)
    # ===================

    # One task per (job_id + page)
    job_tasks.create_index(
        [("job_id", ASCENDING), ("processing_id", ASCENDING), ("page", ASCENDING)],
        unique=True
    )

    # Fast lookup by celery task id
    job_tasks.create_index(
        [("celery_task_id", ASCENDING)],
        unique=True
    )

    # Used for progress polling
    job_tasks.create_index(
        [("job_id", ASCENDING), ("state", ASCENDING)]
    )

    # Used for cleanup & ordering
    job_tasks.create_index(
        [("created_at", DESCENDING)]
    )

    # ===================
    # Users
    # ===================
    users_collection.create_index(
        [("email", ASCENDING)],
        unique=True
    )

    # ===================
    # Payments
    # ===================
    payments_collection.create_index(
        [("reference", ASCENDING)],
        unique=True
    )

    payments_collection.create_index(
        [("user_id", ASCENDING)]
    )

    payments_collection.create_index(
        [("status", ASCENDING)]
    )

    payments_collection.create_index(
        [("created_at", DESCENDING)]
    )
