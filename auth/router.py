import random
from celery import Celery
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Form
from mongo import users_collection
from core.security import (
    hash_password,
    verify_password,
    create_access_token
)
celery = Celery("worker")
celery.config_from_object("celeryconfig")

router = APIRouter(prefix="/auth", tags=["Auth"])

@router.post("/register")
def register(
    email: str = Form(...),
    password: str = Form(...)
):
    if users_collection.find_one({"email": email}):
        raise HTTPException(400, "Email already registered")

    verification_code = f"{random.randint(10000, 99999)}"

    users_collection.insert_one({
        "email": email,
        "password_hash": hash_password(password),
        "credits": 10,
        "email_verified": False,
        "email_verification_code": verification_code,
        "email_verification_expires": datetime.utcnow() + timedelta(minutes=10),
        "created_at": datetime.utcnow()
    })

    celery.send_task(
        "tasks.send_verification_code_email",
        args=[email, verification_code]
    )

    return {
        "message": "Account created. Please verify your email with the code sent."
    }


@router.post("/verify-email-code")
def verify_email_code(
    email: str = Form(...),
    code: str = Form(...)
):
    user = users_collection.find_one({"email": email})

    if not user:
        raise HTTPException(404, "User not found")

    if user.get("email_verified"):
        return {"message": "Email already verified"}

    if user.get("email_verification_code") != code:
        raise HTTPException(400, "Invalid verification code")

    if user.get("email_verification_expires") < datetime.utcnow():
        raise HTTPException(400, "Verification code expired")

    users_collection.update_one(
        {"_id": user["_id"]},
        {"$set": {
            "email_verified": True,
            "email_verified_at": datetime.utcnow()
        },
         "$unset": {
            "email_verification_code": "",
            "email_verification_expires": ""
         }}
    )

    return {"message": "Email verified successfully"}


@router.post("/login")
def login(
    email: str = Form(...),
    password: str = Form(...)
):
    user = users_collection.find_one({"email": email})
    if not user:
        raise HTTPException(401, "Invalid credentials")

    if not verify_password(password, user["password_hash"]):
        raise HTTPException(401, "Invalid credentials")

    if not user.get("email_verified"):
        raise HTTPException(
            403,
            "Please verify your email before logging in"
        )

    token = create_access_token(email)

    return {
        "access_token": token,
        "token_type": "bearer",
        "credits": user["credits"]
    }
