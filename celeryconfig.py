import os
from dotenv import load_dotenv
load_dotenv()


broker_url = os.getenv("REDIS_BROKER", "redis://localhost:6379/0")
result_backend = os.getenv("REDIS_BACKEND", "redis://localhost:6379/1")

task_serializer = "json"
result_serializer = "json"
accept_content = ["json"]
timezone = "UTC"
enable_utc = True
result_expires = 3600
