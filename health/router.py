from fastapi import APIRouter
from datetime import datetime
from mongo import client

router = APIRouter(prefix="/health", tags=["Health"])

# ------------------------------------
# 1️⃣ WAKE-UP ENDPOINT
# ------------------------------------
@router.get("/wake")
def wake_up():
    """
    Called silently by frontend on site load.
    Purpose: wake Render instance.
    """
    return {
        "status": "waking",
        "timestamp": datetime.utcnow().isoformat()
    }


# ------------------------------------
# 2️⃣ READINESS CHECK
# ------------------------------------
@router.get("/ready")
def readiness_check():
    """
    Frontend calls this before uploads / processing.
    If ready=false → show 'Server waking up...'
    """

    mongo_ok = False

    # --- MongoDB readiness ---
    try:
        client.admin.command("ping")
        mongo_ok = True
    except Exception:
        mongo_ok = False

    return {
        "ready": mongo_ok,
        "mongo": mongo_ok,
        "timestamp": datetime.utcnow().isoformat()
    }
