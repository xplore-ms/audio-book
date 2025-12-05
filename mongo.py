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
jobs_collection = db["jobs"]

def ensure_indexes():
    # index job_id unique
    jobs_collection.create_index([("job_id", ASCENDING)], unique=True)
    # optional index by created_at
    jobs_collection.create_index([("created_at", ASCENDING)])
