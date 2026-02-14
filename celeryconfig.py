import os
from dotenv import load_dotenv
load_dotenv()


from app.core import config

broker_url = config.REDIS_BROKER
result_backend = config.REDIS_BACKEND

task_serializer = "json"
result_serializer = "json"
accept_content = ["json"]
timezone = "UTC"
enable_utc = True
result_expires = 3600
