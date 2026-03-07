from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import datetime, timedelta
import requests
from app.db.mongo import users_collection, payments_collection, subscriptions_collection
from app.core.dependencies import get_current_user
from pydantic import BaseModel

from app.core import config

BASE_PRICE_KOBO = 5000  # ₦50 per credit

PAYSTACK_SECRET = config.PAYSTACK_SECRET
PAYSTACK_BASE = config.PAYSTACK_BASE

router = APIRouter(prefix="/payments", tags=["Payments"])

# ---------------- FX CONFIG ----------------
FX_API_URL = "https://open.er-api.com/v6/latest/USD"
FX_CACHE_TTL = timedelta(minutes=10)

_fx_cache = {"rate": None, "expires_at": None}
# ------------------------------------------


PLAN_MAP = {
    "starter": {"credits": 50, "price_ngn": 1000},
    "professional": {"credits": 120, "price_ngn": 2000},
    "mastery": {"credits": 500, "price_ngn": 5000},
}


class InitiatePaymentRequest(BaseModel):
    plan_id: str
    callback_url: str | None = None


def get_plan_details(plan_id: str):
    if plan_id not in PLAN_MAP:
        raise HTTPException(400, "Invalid plan ID")
    return PLAN_MAP[plan_id]


def get_usd_to_ngn_rate() -> float:
    """
    Fetch real-time USD → NGN rate with simple caching
    """
    now = datetime.utcnow()

    if (
        _fx_cache["rate"] is not None
        and _fx_cache["expires_at"] is not None
        and now < _fx_cache["expires_at"]
    ):
        return _fx_cache["rate"]

    try:
        res = requests.get(FX_API_URL, timeout=5)
        res.raise_for_status()
        data = res.json()

        rate = data["rates"]["NGN"]

        _fx_cache["rate"] = rate
        _fx_cache["expires_at"] = now + FX_CACHE_TTL

        return rate
    except Exception:
        # Fallback to last known rate or safe default
        return _fx_cache["rate"] or 1600.0


def calculate_upgrade_price(user_id, new_plan_id: str) -> float:
    """
    Returns the final NGN price after upgrade proration
    """
    plan = get_plan_details(new_plan_id)
    amount_ngn = plan["price_ngn"]

    sub = subscriptions_collection.find_one({"user_id": user_id, "status": "active"})

    if not sub or not sub.get("plan_id"):
        return amount_ngn

    current_plan_id = sub["plan_id"]

    if current_plan_id not in PLAN_MAP:
        return amount_ngn

    current_price = PLAN_MAP[current_plan_id]["price_ngn"]

    if amount_ngn <= current_price:
        return amount_ngn

    now = datetime.utcnow()
    started_at = sub.get("started_at", now - timedelta(days=1))

    total_cycle_days = 30.0
    time_elapsed = now - started_at

    days_used = min(total_cycle_days, time_elapsed.total_seconds() / (24 * 3600))

    days_remaining = max(0, total_cycle_days - days_used)

    unused_value = (days_remaining / total_cycle_days) * current_price

    amount_ngn = max(0, amount_ngn - unused_value)

    return round(amount_ngn, 2)


# ------------------ PRICE QUOTE ------------------
@router.get("/quote")
def get_price_quote(
    plan_id: str = Query(...),
    currency: str = Query("NGN"),
    user_id: str | None = Query(None),
):
    plan = get_plan_details(plan_id)
    amount_ngn = plan["price_ngn"]

    # Upgrade Logic (Prorated)
    is_upgrade = False
    if user_id:
        user = users_collection.find_one({"email": user_id})
        if user:
            new_price = calculate_upgrade_price(user["_id"], plan_id)

            if new_price < plan["price_ngn"]:
                is_upgrade = True

            amount_ngn = new_price

    if currency == "USD":
        usd_to_ngn = get_usd_to_ngn_rate()
        amount_usd = round(amount_ngn / usd_to_ngn, 2)

        return {
            "plan_id": plan_id,
            "credits": plan["credits"],
            "currency": "USD",
            "amount": amount_usd,
            "rate": usd_to_ngn,
            "display": f"${amount_usd}",
            "is_upgrade": is_upgrade,
        }

    return {
        "plan_id": plan_id,
        "credits": plan["credits"],
        "currency": "NGN",
        "amount": amount_ngn,
        "display": f"₦{amount_ngn:,}",
        "is_upgrade": is_upgrade,
    }


# ------------------ INITIATE PAYMENT ------------------
@router.post("/initiate")
def initiate_payment(payload: InitiatePaymentRequest, user=Depends(get_current_user)):
    plan = get_plan_details(payload.plan_id)
    credits = plan["credits"]
    amount_ngn = plan["price_ngn"]

    # Upgrade Logic (Prorated)
    amount_ngn = calculate_upgrade_price(user["_id"], payload.plan_id)

    amount_kobo = int(amount_ngn * 100)

    paystack_payload = {
        "email": user["email"],
        "amount": amount_kobo,
        "currency": "NGN",  # ALWAYS NGN
        "metadata": {
            "plan_id": payload.plan_id,
            "credits": credits,
            "user_id": str(user["_id"]),
        },
    }

    if payload.callback_url:
        paystack_payload["callback_url"] = payload.callback_url

    res = requests.post(
        f"{PAYSTACK_BASE}/transaction/initialize",
        headers={
            "Authorization": f"Bearer {PAYSTACK_SECRET}",
            "Content-Type": "application/json",
        },
        json=paystack_payload,
    )

    if not res.ok:
        paystack_error = res.json().get("message", res.text)
        raise HTTPException(400, f"Paystack initialization failed: {paystack_error}")

    data = res.json()["data"]

    payments_collection.insert_one(
        {
            "reference": data["reference"],
            "user_id": user["_id"],
            "credits": credits,
            "amount": amount_kobo,
            "plan_id": payload.plan_id,
            "status": "pending",
            "created_at": datetime.utcnow(),
        }
    )

    return {
        "authorization_url": data["authorization_url"],
        "reference": data["reference"],
    }


# ------------------ VERIFY PAYMENT ------------------
@router.post("/verify/{reference}")
def verify_payment(reference: str, user=Depends(get_current_user)):
    # Atomic status transition to prevent double processing (e.g. React 18 double call in dev)
    result = payments_collection.update_one(
        {"reference": reference, "status": "pending"}, {"$set": {"status": "verifying"}}
    )

    payment = payments_collection.find_one({"reference": reference})
    if not payment:
        raise HTTPException(404, "Payment not found")

    if result.modified_count == 0:
        if payment["status"] == "success":
            return {"message": "Already verified"}
        if payment["status"] == "verifying":
            raise HTTPException(400, "Payment is already being verified")
        raise HTTPException(
            400, f"Payment has invalid status for verification: {payment['status']}"
        )

    if user["_id"] != payment["user_id"]:
        # Revert status if unauthorized
        payments_collection.update_one(
            {"reference": reference}, {"$set": {"status": "pending"}}
        )
        raise HTTPException(403, "Unauthorized verification attempt")

    res = requests.get(
        f"{PAYSTACK_BASE}/transaction/verify/{reference}",
        headers={
            "Authorization": f"Bearer {PAYSTACK_SECRET}",
        },
    )

    if not res.ok:
        payments_collection.update_one(
            {"reference": reference}, {"$set": {"status": "pending"}}
        )
        raise HTTPException(400, f"Verification failed: {res.text}")

    data = res.json()["data"]
    if data["status"] != "success":
        payments_collection.update_one(
            {"reference": reference}, {"$set": {"status": "pending"}}
        )
        raise HTTPException(400, "Payment not successful")

    now = datetime.utcnow()
    expiry = now + timedelta(days=30)
    batch = {
        "credits": payment["credits"],
        "remaining_credits": payment["credits"],
        "purchased_at": now,
        "expires_at": expiry,
        "reference": reference,
        "status": "active",
    }

    users_collection.update_one(
        {"_id": payment["user_id"]},
        {
            "$inc": {"credits": payment["credits"]},
            "$set": {"active_plan_id": payment.get("plan_id")},
            "$push": {"credit_batches": batch},
        },
    )

    # Manage Subscriptions Collection
    subscriptions_collection.update_one(
        {"user_id": payment["user_id"]},
        {
            "$set": {
                "plan_id": payment.get("plan_id"),
                "status": "active",
                "started_at": now,
                "expires_at": expiry,
                "last_reference": reference,
                "updated_at": now,
            }
        },
        upsert=True,
    )

    payments_collection.update_one(
        {"reference": reference},
        {"$set": {"status": "success", "verified_at": now, "expires_at": expiry}},
    )

    return {
        "status": "success",
        "credits_added": payment["credits"],
    }
