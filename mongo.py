# mongo.py
import os
from dotenv import load_dotenv
load_dotenv()

from pymongo import MongoClient, ASCENDING
from datetime import datetime

MONGO_URL = os.getenv("MONGO_URL")
MONGO_DB = os.getenv("MONGO_DB", "pdf_audio")

client = MongoClient(MONGO_URL)
db = client[MONGO_DB]

# Collections
jobs_collection = db["jobs"]
users_collection = db["users"]
payments_collection = db["payments"]  # ✅ NEW


def ensure_indexes():
    # -------------------
    # Jobs
    # -------------------
    jobs_collection.create_index(
        [("job_id", ASCENDING)],
        unique=True
    )
    jobs_collection.create_index(
        [("created_at", ASCENDING)]
    )

    # -------------------
    # Users
    # -------------------
    users_collection.create_index(
        [("email", ASCENDING)],
        unique=True
    )

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
        [("created_at", ASCENDING)]
    )
