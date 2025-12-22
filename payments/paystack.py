import os
import requests
from fastapi import HTTPException
from mongo import users_collection

PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET")
PAYSTACK_BASE = "https://api.paystack.co"


def initiate_payment(email: str, credits: int):
    amount_kobo = credits * 100  # example: 1 credit = ₦1

    res = requests.post(
        f"{PAYSTACK_BASE}/transaction/initialize",
        headers={
            "Authorization": f"Bearer {PAYSTACK_SECRET}",
            "Content-Type": "application/json"
        },
        json={
            "email": email,
            "amount": amount_kobo
        }
    )

    if not res.ok:
        raise HTTPException(400, "Paystack init failed")

    return res.json()["data"]
