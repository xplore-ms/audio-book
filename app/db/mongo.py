# mongo.py
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import OperationFailure

from app.core.config import settings


# Validate required config
if not settings.mongo.URL:
    raise RuntimeError("MONGO_URL must be set in environment (app/core/config.py)")

# Common client options
COMMON_OPTS = {
    "serverSelectionTimeoutMS": settings.mongo.SERVER_SELECTION_TIMEOUT_MS,
    "socketTimeoutMS": settings.mongo.SOCKET_TIMEOUT_MS,
    "tls": settings.mongo.TLS,
    "retryWrites": settings.mongo.RETRY_WRITES,
}

# synchronous (legacy) client for existing sync code
sync_client = MongoClient(settings.mongo.URL, **COMMON_OPTS)
sync_db = sync_client[settings.mongo.DB]


# Collections (sync) - keep names for backward compatibility
jobs_collection = sync_db["jobs"]
job_tasks = sync_db["job_tasks"]
users_collection = sync_db["users"]
payments_collection = sync_db["payments"]
voices_collection = sync_db["voices"]
subscriptions_collection = sync_db["subscriptions"]
activities_collection = sync_db["activities"]
app_settings = sync_db["app_settings"]


# Backwards-compatible aliases
client = sync_client
db = sync_db

# async client for new async repositories
async_client = AsyncIOMotorClient(settings.mongo.URL, **COMMON_OPTS)
async_db = async_client[settings.mongo.DB]


# async collections for new code
jobs_collection_async = async_db["jobs"]
job_tasks_async = async_db["job_tasks"]
users_collection_async = async_db["users"]
payments_collection_async = async_db["payments"]
voices_collection_async = async_db["voices"]
subscriptions_collection_async = async_db["subscriptions"]
activities_collection_async = async_db["activities"]
app_settings_async = async_db["app_settings"]


def ensure_indexes():
    # Keep sync index creation for compatibility; run in startup thread
    # Jobs
    jobs_collection.create_index([("job_id", ASCENDING)], unique=True, background=True)
    jobs_collection.create_index([("user_id", ASCENDING)], background=True)
    jobs_collection.create_index([("status", ASCENDING)], background=True)
    jobs_collection.create_index([("created_at", DESCENDING)], background=True)

    # Job tasks
    job_tasks.create_index(
        [("job_id", ASCENDING), ("processing_id", ASCENDING), ("page", ASCENDING)],
        unique=True,
        background=True,
    )
    # Make celery_task_id index partial to avoid unique constraint on missing/null values
    try:
        job_tasks.create_index(
            [("celery_task_id", ASCENDING)],
            unique=True,
            partialFilterExpression={"celery_task_id": {"$type": "string"}},
            background=True,
        )
    except OperationFailure as e:
        if e.code == 86:  # IndexKeySpecsConflict
            job_tasks.drop_index("celery_task_id_1")
            job_tasks.create_index(
                [("celery_task_id", ASCENDING)],
                unique=True,
                partialFilterExpression={"celery_task_id": {"$type": "string"}},
                background=True,
            )
        else:
            raise

    job_tasks.create_index(
        [("job_id", ASCENDING), ("state", ASCENDING)], background=True
    )
    job_tasks.create_index([("created_at", DESCENDING)], background=True)

    # Users
    users_collection.create_index([("email", ASCENDING)], unique=True, background=True)

    # Payments
    payments_collection.create_index(
        [("reference", ASCENDING)], unique=True, background=True
    )
    payments_collection.create_index([("user_id", ASCENDING)], background=True)
    payments_collection.create_index([("status", ASCENDING)], background=True)
    payments_collection.create_index([("created_at", DESCENDING)], background=True)

    # Voices - use partial index for unique voice_name when present
    try:
        voices_collection.create_index(
            [("voice_name", ASCENDING)],
            unique=True,
            partialFilterExpression={"voice_name": {"$type": "string"}},
            background=True,
        )
    except OperationFailure as e:
        if e.code == 86:
            voices_collection.drop_index("voice_name_1")
            voices_collection.create_index(
                [("voice_name", ASCENDING)],
                unique=True,
                partialFilterExpression={"voice_name": {"$type": "string"}},
                background=True,
            )
        else:
            raise

    voices_collection.create_index([("created_at", DESCENDING)], background=True)

    # Subscriptions
    subscriptions_collection.create_index(
        [("user_id", ASCENDING)], unique=True, background=True
    )
    subscriptions_collection.create_index([("status", ASCENDING)], background=True)

    # Activities
    activities_collection.create_index([("created_at", DESCENDING)], background=True)
    activities_collection.create_index([("user_id", ASCENDING)], background=True)
    activities_collection.create_index([("type", ASCENDING)], background=True)


async def ensure_indexes_async():
    # Async index creation for Motor (await at app startup)
    await jobs_collection_async.create_index(
        [("job_id", ASCENDING)], unique=True, background=True
    )
    await jobs_collection_async.create_index([("user_id", ASCENDING)], background=True)
    await jobs_collection_async.create_index([("status", ASCENDING)], background=True)
    await jobs_collection_async.create_index(
        [("created_at", DESCENDING)], background=True
    )

    await job_tasks_async.create_index(
        [("job_id", ASCENDING), ("processing_id", ASCENDING), ("page", ASCENDING)],
        unique=True,
        background=True,
    )
    try:
        await job_tasks_async.create_index(
            [("celery_task_id", ASCENDING)],
            unique=True,
            background=True,
            partialFilterExpression={"celery_task_id": {"$type": "string"}},
        )
    except OperationFailure as e:
        if e.code == 86:
            await job_tasks_async.drop_index("celery_task_id_1")
            await job_tasks_async.create_index(
                [("celery_task_id", ASCENDING)],
                unique=True,
                background=True,
                partialFilterExpression={"celery_task_id": {"$type": "string"}},
            )
        else:
            raise

    await job_tasks_async.create_index(
        [("job_id", ASCENDING), ("state", ASCENDING)], background=True
    )
    await job_tasks_async.create_index([("created_at", DESCENDING)], background=True)

    await users_collection_async.create_index(
        [("email", ASCENDING)], unique=True, background=True
    )

    await payments_collection_async.create_index(
        [("reference", ASCENDING)], unique=True, background=True
    )
    await payments_collection_async.create_index(
        [("user_id", ASCENDING)], background=True
    )
    await payments_collection_async.create_index(
        [("status", ASCENDING)], background=True
    )
    await payments_collection_async.create_index(
        [("created_at", DESCENDING)], background=True
    )

    try:
        await voices_collection_async.create_index(
            [("voice_name", ASCENDING)],
            unique=True,
            background=True,
            partialFilterExpression={"voice_name": {"$type": "string"}},
        )
    except OperationFailure as e:
        if e.code == 86:
            await voices_collection_async.drop_index("voice_name_1")
            await voices_collection_async.create_index(
                [("voice_name", ASCENDING)],
                unique=True,
                background=True,
                partialFilterExpression={"voice_name": {"$type": "string"}},
            )
        else:
            raise

    await voices_collection_async.create_index(
        [("created_at", DESCENDING)], background=True
    )

    # Subscriptions
    await subscriptions_collection_async.create_index(
        [("user_id", ASCENDING)], unique=True, background=True
    )
    await subscriptions_collection_async.create_index(
        [("status", ASCENDING)], background=True
    )

    # Activities
    await activities_collection_async.create_index(
        [("created_at", DESCENDING)], background=True
    )
    await activities_collection_async.create_index(
        [("user_id", ASCENDING)], background=True
    )
    await activities_collection_async.create_index(
        [("type", ASCENDING)], background=True
    )
