from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
import requests
import os

from mongo import users_collection, payments_collection
from core.dependencies import get_current_user

from pydantic import BaseModel

class InitiatePaymentRequest(BaseModel):
    credits: int

PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET")
PAYSTACK_BASE = "https://api.paystack.co"

router = APIRouter(prefix="/payments", tags=["Payments"])

@router.post("/initiate")
def initiate_payment(
    payload: InitiatePaymentRequest,
    user=Depends(get_current_user)
):
    credits = payload.credits

    if credits <= 0:
        raise HTTPException(400, "Invalid credit amount")

    amount_kobo = credits * 100  # ₦1 = 1 credit

    res = requests.post(
        f"{PAYSTACK_BASE}/transaction/initialize",
        headers={
            "Authorization": f"Bearer {PAYSTACK_SECRET}",
            "Content-Type": "application/json",
        },
        json={
            "email": user["email"],
            "amount": amount_kobo,
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
