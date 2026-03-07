import os
import sys

# Add the backend directory to python path so 'app' can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

# ── 1. Mock heavy external modules BEFORE any app import ──────────────────────
sys.modules["redis"] = MagicMock()
sys.modules["pymongo"] = MagicMock()
sys.modules["motor"] = MagicMock()
sys.modules["bson"] = MagicMock()
sys.modules["bson.objectid"] = MagicMock()
sys.modules["celery"] = MagicMock()
sys.modules["celery.result"] = MagicMock()
sys.modules["celery.app"] = MagicMock()
sys.modules["app.integrations.supabase.client"] = MagicMock()
sys.modules["app.integrations"] = MagicMock()
sys.modules["app.integrations.supabase"] = MagicMock()

# ── 2. Mock config with real string values so nothing blows up at import ──────
mock_config = MagicMock()
mock_settings = MagicMock()
mock_settings.redis.REDIS_BROKER = "redis://localhost:6379/0"
mock_settings.uploads.MAX_UPLOAD_SIZE = 10_000_000
mock_settings.uploads.MAX_PAGES = 100
mock_settings.mail.MAIL_USERNAME = "test"
mock_settings.mail.MAIL_PASSWORD = "test"
mock_settings.security.JWT_SECRET = "test_secret"
mock_settings.supabase.SUPABASE_BUCKET = "test_bucket"
mock_config.settings = mock_settings
mock_config.MONGO_URL = "mongodb://localhost:27017"
mock_config.MONGO_DB = "test_db"
mock_config.PAYSTACK_SECRET = "test_secret"
mock_config.PAYSTACK_BASE = "https://api.paystack.co"
mock_config.SUPABASE_BUCKET = "test_bucket"
sys.modules["app.core.config"] = mock_config

# ── 3. Mock MongoDB collections ───────────────────────────────────────────────
mock_mongo = MagicMock()
mock_mongo.users_collection = MagicMock()
mock_mongo.jobs_collection = MagicMock()
mock_mongo.payments_collection = MagicMock()
mock_mongo.subscriptions_collection = MagicMock()
mock_mongo.system_settings_collection = MagicMock()
mock_mongo.voices_collection = MagicMock()
mock_mongo.activities_collection = MagicMock()
mock_mongo.job_tasks = MagicMock()
mock_mongo.client = MagicMock()
mock_mongo.client.admin.command.return_value = {"ok": 1}

sys.modules["app.db.mongo"] = mock_mongo
sys.modules["app.db"] = MagicMock()

# ── 4. Mock the rate limiter so Redis never actually initialises ───────────────
mock_rate_limiter = MagicMock()
mock_rate_limiter.rate_limit = MagicMock(return_value=None)
sys.modules["app.core.rate_limiter"] = mock_rate_limiter

# ── 5. Now import the app ─────────────────────────────────────────────────────
from app.main import app  # noqa: E402
from app.core.dependencies import get_current_user  # noqa: E402

# ── 6. Test users ─────────────────────────────────────────────────────────────
MOCK_USER = {
    "_id": "user_id_123",
    "email": "test@example.com",
    "role": "user",
    "credits": 100,
}

MOCK_ADMIN = {
    "_id": "admin_id_456",
    "email": "admin@example.com",
    "role": "admin",
    "credits": 100,
}


def mock_get_current_user():
    return MOCK_USER


app.dependency_overrides[get_current_user] = mock_get_current_user


# ── 7. Fixtures ───────────────────────────────────────────────────────────────
@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_client():
    app.dependency_overrides[get_current_user] = lambda: MOCK_ADMIN
    with TestClient(app) as c:
        yield c
    app.dependency_overrides[get_current_user] = mock_get_current_user


@pytest.fixture
def app_with_plan_user():
    """Override the current user to include an active_plan_id for plan-gated endpoints."""
    plan_user = {**MOCK_USER, "active_plan_id": "professional"}
    app.dependency_overrides[get_current_user] = lambda: plan_user
    yield
    app.dependency_overrides[get_current_user] = mock_get_current_user
