from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import datetime, timedelta
import requests
import os
from dotenv import load_dotenv
from app.db.mongo import users_collection, payments_collection
from app.core.dependencies import get_current_user
from pydantic import BaseModel

BASE_PRICE_KOBO = 5000  # ₦50 per credit

load_dotenv()
from app.core import config

PAYSTACK_SECRET = config.PAYSTACK_SECRET
PAYSTACK_BASE = "https://api.paystack.co"

router = APIRouter(prefix="/payments", tags=["Payments"])

# ---------------- FX CONFIG ----------------
FX_API_URL = "https://open.er-api.com/v6/latest/USD"
FX_CACHE_TTL = timedelta(minutes=10)

_fx_cache = {
    "rate": None,
    "expires_at": None
}
# ------------------------------------------


class InitiatePaymentRequest(BaseModel):
    credits: int
    callback_url: str | None = None


def calculate_price_kobo(credits: int) -> int:
    if credits <= 0:
        raise ValueError("Invalid credit amount")
    return credits * BASE_PRICE_KOBO


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


# ------------------ PRICE QUOTE ------------------
@router.get("/quote")
def get_price_quote(
    credits: int = Query(..., gt=0),
    currency: str = Query("NGN")
):
    amount_kobo = calculate_price_kobo(credits)
    amount_ngn = amount_kobo / 100

    if currency == "USD":
        usd_to_ngn = get_usd_to_ngn_rate()
        amount_usd = round(amount_ngn / usd_to_ngn, 2)

        return {
            "credits": credits,
            "currency": "USD",
            "amount": amount_usd,
            "rate": usd_to_ngn,
            "display": f"${amount_usd}",
        }

    return {
        "credits": credits,
        "currency": "NGN",
        "amount": amount_ngn,
        "display": f"₦{amount_ngn:,}",
    }


# ------------------ INITIATE PAYMENT ------------------
@router.post("/initiate")
def initiate_payment(
    payload: InitiatePaymentRequest,
    user=Depends(get_current_user)
):
    credits = payload.credits
    amount_kobo = calculate_price_kobo(credits)

    paystack_payload = {
        "email": user["email"],
        "amount": amount_kobo,
        "currency": "NGN",  # ALWAYS NGN
        "metadata": {
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
        raise HTTPException(400, "Paystack initialization failed")

    data = res.json()["data"]

    payments_collection.insert_one({
        "reference": data["reference"],
        "user_id": user["_id"],
        "credits": credits,
        "amount": amount_kobo,
        "status": "pending",
        "created_at": datetime.utcnow(),
    })

    return {
        "authorization_url": data["authorization_url"],
        "reference": data["reference"],
    }


# ------------------ VERIFY PAYMENT ------------------
@router.post("/verify/{reference}")
def verify_payment(
    reference: str,
    user=Depends(get_current_user)
):
    payment = payments_collection.find_one({"reference": reference})
    if not payment:
        raise HTTPException(404, "Payment not found")

    if payment["status"] == "success":
        return {"message": "Already verified"}

    res = requests.get(
        f"{PAYSTACK_BASE}/transaction/verify/{reference}",
        headers={
            "Authorization": f"Bearer {PAYSTACK_SECRET}",
        },
    )

    if not res.ok:
        raise HTTPException(400, f"Verification failed: {res.text}")

    data = res.json()["data"]
    if data["status"] != "success":
        raise HTTPException(400, "Payment not successful")

    if user["_id"] != payment["user_id"]:
        raise HTTPException(403, "Unauthorized verification attempt")

    users_collection.update_one(
        {"_id": payment["user_id"]},
        {"$inc": {"credits": payment["credits"]}}
    )

    payments_collection.update_one(
        {"reference": reference},
        {"$set": {"status": "success", "verified_at": datetime.utcnow()}}
    )

    return {
        "status": "success",
        "credits_added": payment["credits"],
    }
