import secrets
from celery import Celery
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Form, Request
from fastapi.params import Depends
from core.rate_limiter import rate_limit
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
import re
import logging

celery = Celery("worker")
celery.config_from_object("celeryconfig")

router = APIRouter(prefix="/auth", tags=["Auth"])

# Set up logging safely
logger = logging.getLogger("auth")
logger.setLevel(logging.INFO)

def generate_code(length=5):
    """Generate a cryptographically secure numeric code of given length."""
    return str(secrets.randbelow(10**length - 10**(length-1)) + 10**(length-1))

def is_strong_password(password: str) -> bool:
    """Check password complexity: min 8 chars, upper, lower, digit, special."""
    return bool(re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[\W_]).{8,}$', password))


def get_client_ip(request: Request):
    """Get IP address safely from request headers or client."""
    if request.headers.get("x-forwarded-for"):
        return request.headers["x-forwarded-for"].split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


@router.post("/register")
def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    device_fingerprint_hash: str = Form(...)
):
    ip_address = get_client_ip(request)
    # Rate limit by email + IP
    rate_limit(f"register:{email}", limit=5, window_seconds=300)
    if ip_address:
        rate_limit(f"register_ip:{ip_address}", limit=10, window_seconds=300)

    if users_collection.find_one({"email": email}):
        raise HTTPException(400, "Email already registered")

    if not is_strong_password(password):
        raise HTTPException(
            400,
            "Password must be at least 8 characters, with upper, lower, digit, and symbol"
        )

    credit = 10
    fingerprint_used = users_collection.find_one({
        "device_fingerprint_hash": device_fingerprint_hash,
        "email_verified": True
    })
    if fingerprint_used:
        credit = 0

    verification_code = generate_code()
    user_agent = request.headers.get("user-agent")

    users_collection.insert_one({
        "email": email,
        "password_hash": hash_password(password),
        "credits": credit,
        "has_received_signup_credits": credit > 0,
        "email_verified": False,
        "email_verification_code": verification_code,
        "email_verification_expires": datetime.utcnow() + timedelta(minutes=10),
        "device_fingerprint_hash": device_fingerprint_hash,
        "signup_ip": ip_address,
        "signup_user_agent": user_agent,
        "refresh_token_hash": None,
        "refresh_token_expires": None,
        "is_suspended": False,
        "created_at": datetime.utcnow()
    })

    celery.send_task(
        "tasks.send_verification_code_email",
        args=[email, verification_code]
    )

    logger.info(f"New registration attempt for {email} from IP {ip_address}")

    return {"message": "Account created. Please verify your email with the code sent."}


@router.post("/verify-email-code")
def verify_email_code(
    email: str = Form(...),
    code: str = Form(...)
):
    rate_limit(f"verify-email:{email}", limit=5, window_seconds=300)

    user = users_collection.find_one({"email": email})
    if not user or user.get("email_verification_code") != code:
        raise HTTPException(400, "Invalid email or code")

    if user.get("email_verified"):
        return {"message": "Email already verified"}

    if user.get("email_verification_expires") < datetime.utcnow():
        raise HTTPException(400, "Verification code expired")

    users_collection.update_one(
        {"_id": user["_id"]},
        {"$set": {"email_verified": True, "email_verified_at": datetime.utcnow()},
         "$unset": {"email_verification_code": "", "email_verification_expires": ""}}
    )

    logger.info(f"Email verified for {email}")

    return {"message": "Email verified successfully"}


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...)
):
    ip_address = get_client_ip(request)
    rate_limit(f"login:{email}", limit=5, window_seconds=300)
    if ip_address:
        rate_limit(f"login_ip:{ip_address}", limit=20, window_seconds=300)

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

    logger.info(f"User {email} logged in from IP {ip_address}")

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "credits": user["credits"]
    }


@router.post("/forgot-password")
def forgot_password(request: Request, email: str = Form(...)):
    ip_address = get_client_ip(request)
    rate_limit(f"forgot-password:{email}", limit=3, window_seconds=3600)
    if ip_address:
        rate_limit(f"forgot-password_ip:{ip_address}", limit=10, window_seconds=3600)

    user = users_collection.find_one({"email": email})
    if not user:
        return {"message": "If the email exists, a reset code has been sent"}

    reset_code = generate_code()
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

    logger.info(f"Password reset requested for {email} from IP {ip_address}")

    return {"message": "If the email exists, a reset code has been sent"}


@router.post("/reset-password")
def reset_password(
    email: str = Form(...),
    code: str = Form(...),
    new_password: str = Form(...)
):
    rate_limit(f"reset-password:{email}", limit=5, window_seconds=300)

    user = users_collection.find_one({"email": email})
    if not user or user.get("password_reset_code") != code:
        raise HTTPException(400, "Invalid email or code")

    if user.get("password_reset_expires") < datetime.utcnow():
        raise HTTPException(400, "Reset code expired")

    if not is_strong_password(new_password):
        raise HTTPException(
            400,
            "Password must be at least 8 characters, with upper, lower, digit, and symbol"
        )

    users_collection.update_one(
        {"_id": user["_id"]},
        {"$set": {"password_hash": hash_password(new_password)},
         "$unset": {"password_reset_code": "", "password_reset_expires": "",
                    "refresh_token_hash": "", "refresh_token_expires": ""}}
    )

    logger.info(f"Password reset for {email}")

    return {"message": "Password reset successfully"}

@router.get("/me")
def get_me(user=Depends(get_current_user)):
    return {
        "email": user["email"],
        "credits": user.get("credits", 0)
    }
