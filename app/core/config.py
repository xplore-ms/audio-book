import os
from dotenv import load_dotenv

load_dotenv()

ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "http://localhost:5173")

# Security
JWT_SECRET = os.getenv("JWT_SECRET", "token-secret-change-me")
if not JWT_SECRET or JWT_SECRET == "token-secret-change-me":
	raise RuntimeError("JWT_SECRET must be set to a strong secret in production")

# Mongo configuration
MONGO_URL = os.getenv("MONGO_URL")
MONGO_DB = os.getenv("MONGO_DB", "pdf_audio")

# Supabase / Storage
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "reading_app")

# Upload limits
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", str(50 * 1024 * 1024)))
MAX_PAGES = int(os.getenv("MAX_PAGES", "500"))
MAX_PAGES_PER_JOB = int(os.getenv("MAX_PAGES_PER_JOB", "20"))

# Optional Mongo client tuning (ms)
MONGO_SERVER_SELECTION_TIMEOUT_MS = int(os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "5000"))
MONGO_SOCKET_TIMEOUT_MS = int(os.getenv("MONGO_SOCKET_TIMEOUT_MS", str(300_000)))
MONGO_RETRY_WRITES = os.getenv("MONGO_RETRY_WRITES", "1") not in ("0", "false", "False")
MONGO_TLS = os.getenv("MONGO_TLS", "1") not in ("0", "false", "False")

# Redis / Celery
REDIS_BROKER = os.getenv("REDIS_BROKER", "redis://localhost:6379/0")
REDIS_BACKEND = os.getenv("REDIS_BACKEND", "redis://localhost:6379/1")

# Supabase Auth / Client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Payment
PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET")

# Mail
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
