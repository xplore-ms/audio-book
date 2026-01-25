import random
from celery import Celery
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Form
from fastapi.params import Depends
from core.dependencies import get_current_user, JWT_SECRET, JWT_ALGO
from jose import jwt
from mongo import users_collection
from core.security import (
    create_refresh_token,
    hash_password,
    hash_refresh_token,
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
        "credits": 50,
        "email_verified": False,
        "email_verification_code": verification_code,
        "email_verification_expires": datetime.utcnow() + timedelta(minutes=10),
        "refresh_token_hash": None,
        "refresh_token_expires": None,
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
    if not user or not verify_password(password, user["password_hash"]):
        raise HTTPException(401, "Invalid credentials")

    if not user.get("email_verified"):
        raise HTTPException(403, "Please verify your email")

    access_token = create_access_token(email)
    refresh_token = create_refresh_token(email)

    users_collection.update_one(
        {"_id": user["_id"]},
        {"$set": {
            "refresh_token_hash": hash_refresh_token(refresh_token),
            "refresh_token_expires": datetime.utcnow() + timedelta(days=30)
        }}
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "credits": user["credits"]
    }

@router.post("/refresh-token")
def refresh_token(refresh_token: str = Form(...)):
    try:
        payload = jwt.decode(refresh_token, JWT_SECRET, algorithms=[JWT_ALGO])
    except Exception:
        raise HTTPException(401, "Invalid refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(401, "Invalid token type")

    email = payload["sub"]
    user = users_collection.find_one({"email": email})

    if not user:
        raise HTTPException(401, "User not found")

    if user["refresh_token_expires"] < datetime.utcnow():
        raise HTTPException(401, "Refresh token expired")

    if user["refresh_token_hash"] != hash_refresh_token(refresh_token):
        raise HTTPException(401, "Token mismatch")

    # Rotate tokens
    new_access = create_access_token(email)
    new_refresh = create_refresh_token(email)

    users_collection.update_one(
        {"_id": user["_id"]},
        {"$set": {
            "refresh_token_hash": hash_refresh_token(new_refresh),
            "refresh_token_expires": datetime.utcnow() + timedelta(days=30)
        }}
    )

    return {
        "access_token": new_access,
        "refresh_token": new_refresh,
        "token_type": "bearer"
    }


@router.get("/me")
def get_me(user=Depends(get_current_user)):
    return {
        "email": user["email"],
        "credits": user.get("credits", 0)
    }


@router.post("/logout")
def logout(user=Depends(get_current_user)):
    users_collection.update_one(
        {"email": user["email"]},
        {"$unset": {
            "refresh_token_hash": "",
            "refresh_token_expires": ""
        }}
    )
    return {"message": "Logged out successfully"}


@router.post("/forgot-password")
def forgot_password(email: str = Form(...)):
    user = users_collection.find_one({"email": email})

    if not user:
        raise HTTPException(404, "User not found")

    reset_code = f"{random.randint(10000, 99999)}"

    users_collection.update_one(
        {"_id": user["_id"]},
        {"$set": {
            "password_reset_code": reset_code,
            "password_reset_expires": datetime.utcnow() + timedelta(minutes=10)
        }}
    )

    celery.send_task(
        "tasks.send_reset_code_email",
        args=[email, reset_code]
    )

    return {"message": "Password reset code sent to your email"}


@router.post("/reset-password")
def reset_password(
    email: str = Form(...),
    code: str = Form(...),
    new_password: str = Form(...)
):
    user = users_collection.find_one({"email": email})

    if not user:
        raise HTTPException(404, "User not found")

    if user.get("password_reset_code") != code:
        raise HTTPException(400, "Invalid reset code")

    if user.get("password_reset_expires") < datetime.utcnow():
        raise HTTPException(400, "Reset code expired")

    users_collection.update_one(
        {"_id": user["_id"]},
        {"$set": {
            "password_hash": hash_password(new_password)
        },
         "$unset": {
            "password_reset_code": "",
            "password_reset_expires": ""
         }}
    )

    return {"message": "Password reset successfully"}
