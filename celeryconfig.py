from app.core.config import settings

broker_url = settings.redis.REDIS_BROKER
result_backend = settings.redis.REDIS_BACKEND


task_serializer = "json"
result_serializer = "json"
accept_content = ["json"]
timezone = "UTC"
enable_utc = True
result_expires = 3600
broker_connection_retry_on_startup = True
