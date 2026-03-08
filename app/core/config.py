import os
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

MISSING_ENV_VARS = []


def get_env_required(name: str) -> str:
    """Helper to get a required environment variable or raise a RuntimeError."""
    val = os.getenv(name)
    if not val:
        MISSING_ENV_VARS.append(name)
        return ""
    return val


def check_missing_env_vars():
    if MISSING_ENV_VARS:
        raise RuntimeError(
            f"\n❌ CONFIG ERROR: Missing required environment variable: '{MISSING_ENV_VARS}'\n"
            f"Please ensure it is set in your environment or defined in your .env file."
        )


class MongoSettings(BaseModel):
    URL: str = get_env_required("MONGO_URL")
    DB: str = get_env_required("MONGO_DB")
    SERVER_SELECTION_TIMEOUT_MS: int = int(
        os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "5000")
    )
    SOCKET_TIMEOUT_MS: int = int(os.getenv("MONGO_SOCKET_TIMEOUT_MS", str(300_000)))
    RETRY_WRITES: bool = os.getenv("MONGO_RETRY_WRITES", "1") not in (
        "0",
        "false",
        "False",
    )
    TLS: bool = os.getenv("MONGO_TLS", "1") not in ("0", "false", "False")


class SecuritySettings(BaseModel):
    JWT_SECRET: str = get_env_required("JWT_SECRET")


class StorageSettings(BaseModel):
    SUPABASE_URL: str = get_env_required("SUPABASE_URL")
    SUPABASE_KEY: str = get_env_required("SUPABASE_KEY")
    SUPABASE_BUCKET: str = get_env_required("SUPABASE_BUCKET")


class RedisSettings(BaseModel):
    REDIS_BROKER: str = (
        os.getenv("CELERY_BROKER_URL")
        or os.getenv("REDIS_URL")
        or get_env_required("REDIS_BROKER")
    )
    REDIS_BACKEND: str = (
        os.getenv("RESULT_BACKEND")
        or os.getenv("REDIS_URL")
        or get_env_required("REDIS_BACKEND")
    )


class UploadSettings(BaseModel):
    MAX_UPLOAD_SIZE: int = int(os.getenv("MAX_UPLOAD_SIZE", str(50 * 1024 * 1024)))
    MAX_PAGES: int = int(os.getenv("MAX_PAGES", "2000"))
    MAX_PAGES_PER_JOB: int = int(os.getenv("MAX_PAGES_PER_JOB", "4"))


class PaymentSettings(BaseModel):
    PAYSTACK_SECRET: str = get_env_required("PAYSTACK_SECRET")
    PAYSTACK_BASE: str = get_env_required("PAYSTACK_BASE")


class MailSettings(BaseModel):
    MAIL_USERNAME: str = get_env_required("MAIL_USERNAME")
    MAIL_PASSWORD: str = get_env_required("MAIL_PASSWORD")
    MAIL_SERVER: str = get_env_required("MAIL_SERVER")
    MAIL_PORT: int = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USE_TLS: bool = os.getenv("MAIL_USE_TLS", "1") not in ("0", "false", "False")
    MAIL_USE_SSL: bool = os.getenv("MAIL_USE_SSL", "0") not in ("0", "false", "False")
    # MAIL_DEFAULT_SENDER: str = get_env_required("MAIL_DEFAULT_SENDER")


class Settings(BaseModel):
    ALLOWED_ORIGIN: str = os.getenv("ALLOWED_ORIGIN") or os.getenv(
        "ALLOWED_ORIGINS", "*"
    )
    GENAI_API_KEY: str = get_env_required("GENAI_API_KEY")
    mongo: MongoSettings = MongoSettings()
    security: SecuritySettings = SecuritySettings()
    storage: StorageSettings = StorageSettings()
    redis: RedisSettings = RedisSettings()
    uploads: UploadSettings = UploadSettings()
    payment: PaymentSettings = PaymentSettings()
    mail: MailSettings = MailSettings()


settings = Settings()
check_missing_env_vars()

# Final validation is handled by get_env_required during instantiation.
# If these lines are reached, it means all critical variables are present.

ALLOWED_ORIGIN = settings.ALLOWED_ORIGIN
JWT_SECRET = settings.security.JWT_SECRET
MONGO_URL = settings.mongo.URL
MONGO_DB = settings.mongo.DB
SUPABASE_BUCKET = settings.storage.SUPABASE_BUCKET
MAX_UPLOAD_SIZE = settings.uploads.MAX_UPLOAD_SIZE
MAX_PAGES = settings.uploads.MAX_PAGES
MAX_PAGES_PER_JOB = settings.uploads.MAX_PAGES_PER_JOB
MONGO_SERVER_SELECTION_TIMEOUT_MS = settings.mongo.SERVER_SELECTION_TIMEOUT_MS
MONGO_SOCKET_TIMEOUT_MS = settings.mongo.SOCKET_TIMEOUT_MS
MONGO_RETRY_WRITES = settings.mongo.RETRY_WRITES
MONGO_TLS = settings.mongo.TLS
REDIS_BROKER = settings.redis.REDIS_BROKER
REDIS_BACKEND = settings.redis.REDIS_BACKEND
SUPABASE_URL = settings.storage.SUPABASE_URL
SUPABASE_KEY = settings.storage.SUPABASE_KEY
PAYSTACK_SECRET = settings.payment.PAYSTACK_SECRET
PAYSTACK_BASE = settings.payment.PAYSTACK_BASE
MAIL_USERNAME = settings.mail.MAIL_USERNAME
MAIL_PASSWORD = settings.mail.MAIL_PASSWORD
