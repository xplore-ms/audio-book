from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import datetime
import requests
import os

from mongo import users_collection, payments_collection
from core.dependencies import get_current_user

from pydantic import BaseModel
BASE_PRICE_KOBO = 500  # ₦5
DISCOUNT_PRICE_KOBO = 250  # ₦2.5
DISCOUNT_THRESHOLD = 500

class InitiatePaymentRequest(BaseModel):
    credits: int

PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET")
PAYSTACK_BASE = "https://api.paystack.co"

router = APIRouter(prefix="/payments", tags=["Payments"])

def calculate_price_kobo(credits: int) -> int:
    if credits <= 0:
        raise ValueError("Invalid credit amount")

    price_per_credit = (
        DISCOUNT_PRICE_KOBO if credits >= DISCOUNT_THRESHOLD else BASE_PRICE_KOBO
    )
    return credits * price_per_credit


@router.get("/quote")
def get_price_quote(
    credits: int = Query(..., gt=0),
    currency: str = Query("NGN")
):
    amount_kobo = calculate_price_kobo(credits)

    if currency == "USD":
        # simple fixed conversion (safe + predictable)
        USD_RATE = 1600  # ₦1600 = $1 (you can update later)
        amount_usd = round((amount_kobo / 100) / USD_RATE, 2)

        return {
            "credits": credits,
            "currency": "USD",
            "amount": amount_usd,
            "display": f"${amount_usd}",
        }

    return {
        "credits": credits,
        "currency": "NGN",
        "amount": amount_kobo / 100,
        "display": f"₦{amount_kobo / 100:,}",
    }


@router.post("/initiate")
def initiate_payment(
    payload: InitiatePaymentRequest,
    user=Depends(get_current_user)
):
    credits = payload.credits
    amount_kobo = calculate_price_kobo(credits)

    res = requests.post(
        f"{PAYSTACK_BASE}/transaction/initialize",
        headers={
            "Authorization": f"Bearer {PAYSTACK_SECRET}",
            "Content-Type": "application/json",
        },
        json={
            "email": user["email"],
            "amount": amount_kobo,
            "currency": "NGN",  # IMPORTANT: always NGN
            "metadata": {
                "credits": credits,
                "user_id": str(user["_id"]),
            },
        },
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
        raise HTTPException(400, "Verification failed")

    data = res.json()["data"]
    if data["status"] != "success":
        raise HTTPException(400, "Payment not successful")

    if user["_id"] != payment["user_id"]:
        raise HTTPException(403, "Unauthorized verification attempt")
    # Credit user
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
