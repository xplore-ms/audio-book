from datetime import datetime
from typing import Optional, Dict, Any
from app.db.mongo import activities_collection


def log_activity(
    user_id: str,
    activity_type: str,
    description: str,
    metadata: Optional[Dict[str, Any]] = None,
    is_admin_action: bool = False,
):
    """
    Log an activity to the database.

    activity_type: e.g., 'plan_change', 'email_verified', 'credit_adjustment', 'job_started', etc.
    """
    activity = {
        "user_id": user_id,
        "type": activity_type,
        "description": description,
        "metadata": metadata or {},
        "is_admin_action": is_admin_action,
        "created_at": datetime.utcnow(),
    }
    activities_collection.insert_one(activity)


async def log_activity_async(
    user_id: str,
    activity_type: str,
    description: str,
    metadata: Optional[Dict[str, Any]] = None,
    is_admin_action: bool = False,
):
    """
    Log an activity to the database asynchronously.
    """
    from app.db.mongo import activities_collection_async

    activity = {
        "user_id": user_id,
        "type": activity_type,
        "description": description,
        "metadata": metadata or {},
        "is_admin_action": is_admin_action,
        "created_at": datetime.utcnow(),
    }
    await activities_collection_async.insert_one(activity)
