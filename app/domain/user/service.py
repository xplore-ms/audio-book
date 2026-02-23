import secrets
from datetime import datetime, timedelta
from typing import Optional
import asyncio

from celery import Celery

from app.domain.user.repository import UserRepository
from app.domain.user.schemas import UserInDB, UserCreate
from jose import jwt
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
    JWT_SECRET,
    JWT_ALGO,
)
from app.db import mongo

celery = Celery("worker")
celery.config_from_object("celeryconfig")


def _generate_code(length=5) -> str:
    return str(secrets.randbelow(10**length - 10**(length-1)) + 10**(length-1))


def _is_strong_password(password: str) -> bool:
    import re
    return bool(re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[\W_]).{8,}$', password))


class UserService:
    def __init__(self, repo: UserRepository):
        self.repo = repo

    @classmethod
    def default(cls):
        return cls(UserRepository(mongo.users_collection_async))

    async def register_user(self, user_in: UserCreate, ip_address: Optional[str], user_agent: Optional[str]):
        # Dup check
        existing = await self.repo.find_by_email(user_in.email)
        if existing:
            raise ValueError("Email already registered")

        if not _is_strong_password(user_in.password):
            raise ValueError("Password does not meet complexity requirements")

        credit = 10
        fingerprint_used = await self.repo.find_by_filter({
            "device_fingerprint_hash": user_in.device_fingerprint_hash,
            "email_verified": True
        })
        if fingerprint_used:
            credit = 0

        verification_code = _generate_code()

        user_db = UserInDB(
            email=user_in.email,
            password_hash=hash_password(user_in.password),
            credits=credit,
            has_received_signup_credits=(credit > 0),
            email_verified=False,
            email_verification_code=verification_code,
            email_verification_expires=(datetime.utcnow() + timedelta(minutes=10)),
            device_fingerprint_hash=user_in.device_fingerprint_hash,
            signup_ip=ip_address,
            signup_user_agent=user_agent,
            refresh_token_hash=None,
            refresh_token_expires=None,
            is_suspended=False,
            created_at=datetime.utcnow()
        )

        await self.repo.insert(user_db)

        # send celery task off the event loop to avoid blocking
        await asyncio.to_thread(celery.send_task, "tasks.send_verification_code_email", [user_in.email, verification_code])

        return {"message": "Account created. Please verify your email with the code sent."}

    async def verify_email_code(self, email: str, code: str):
        user = await self.repo.find_by_email(email)
        if not user or user.get("email_verification_code") != code:
            raise ValueError("Invalid email or code")

        if user.get("email_verified"):
            return {"message": "Email already verified"}

        if user.get("email_verification_expires") and user.get("email_verification_expires") < datetime.utcnow():
            raise ValueError("Verification code expired")

        update = {"$set": {"email_verified": True, "email_verified_at": datetime.utcnow()}, "$unset": {"email_verification_code": "", "email_verification_expires": ""}}
        await self.repo.update_by_id(user["_id"], update)

        return {"message": "Email verified successfully"}

    async def login_user(self, email: str, password: str):
        user = await self.repo.find_by_email(email)
        if not user or not verify_password(password, user["password_hash"]):
            raise PermissionError("Invalid credentials")

        if not user.get("email_verified"):
            raise PermissionError("Please verify your email")

        access_token = create_access_token(email)
        refresh_token = create_refresh_token(email)

        update = {"$set": {
            "refresh_token_hash": hash_refresh_token(refresh_token),
            "refresh_token_expires": datetime.utcnow() + timedelta(days=30)
        }}
        await self.repo.update_by_id(user["_id"], update)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "credits": user.get("credits", 0)
        }

    async def forgot_password(self, email: str):
        user = await self.repo.find_by_email(email)
        if not user:
            return {"message": "If the email exists, a reset code has been sent"}

        reset_code = _generate_code()
        await self.repo.update_by_id(user["_id"], {"$set": {
            "password_reset_code": reset_code,
            "password_reset_expires": datetime.utcnow() + timedelta(minutes=10)
        }})

        await asyncio.to_thread(celery.send_task, "tasks.send_reset_code_email", [email, reset_code])

        return {"message": "If the email exists, a reset code has been sent"}

    async def reset_password(self, email: str, code: str, new_password: str):
        user = await self.repo.find_by_email(email)
        if not user or user.get("password_reset_code") != code:
            raise ValueError("Invalid email or code")

        if user.get("password_reset_expires") and user.get("password_reset_expires") < datetime.utcnow():
            raise ValueError("Reset code expired")

        if not _is_strong_password(new_password):
            raise ValueError("Password does not meet complexity requirements")

        await self.repo.update_by_id(user["_id"], {"$set": {"password_hash": hash_password(new_password)}, "$unset": {"password_reset_code": "", "password_reset_expires": "", "refresh_token_hash": "", "refresh_token_expires": ""}})

        return {"message": "Password reset successfully"}

    async def get_me(self, user: dict):
        # Do not expose sensitive fields
        return {"email": user["email"], "credits": user.get("credits", 0)}

    async def refresh_user_token(self, refresh_token: str):
        try:
            payload = jwt.decode(refresh_token, JWT_SECRET, algorithms=[JWT_ALGO])
            if payload.get("type") != "refresh":
                raise ValueError("Invalid token type")
            email = payload.get("sub")
            if not email:
                raise ValueError("Invalid token payload")
        except Exception:
            raise ValueError("Invalid or expired refresh token")

        user = await self.repo.find_by_email(email)
        if not user or user.get("is_suspended"):
            raise ValueError("User not found or suspended")

        # Verify hash match
        token_hash = hash_refresh_token(refresh_token)
        if user.get("refresh_token_hash") != token_hash:
            raise ValueError("Invalid refresh token")

        # Verify expiration
        if user.get("refresh_token_expires") and user.get("refresh_token_expires") < datetime.utcnow():
            raise ValueError("Refresh token expired")

        # Generate new tokens
        new_access_token = create_access_token(email)
        new_refresh_token = create_refresh_token(email)

        # Update user with new refresh token hash
        update = {"$set": {
            "refresh_token_hash": hash_refresh_token(new_refresh_token),
            "refresh_token_expires": datetime.utcnow() + timedelta(days=30)
        }}
        await self.repo.update_by_id(user["_id"], update)

        return {
            "access_token": new_access_token,
            "refresh_token": new_refresh_token,
            "token_type": "bearer"
        }

