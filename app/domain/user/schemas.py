from datetime import datetime
from pydantic import BaseModel, EmailStr
from typing import Optional


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    device_fingerprint_hash: str

    model_config = {"extra": "forbid"}


class UserPublic(BaseModel):
    email: EmailStr
    credits: int = 0

    model_config = {"extra": "forbid"}


class UserInDB(BaseModel):
    email: EmailStr
    password_hash: str
    credits: int = 0
    email_verified: bool = False
    device_fingerprint_hash: Optional[str] = None
    created_at: Optional[datetime] = None

    # Preserve common live fields; optional to remain compatible with existing records
    has_received_signup_credits: Optional[bool] = None
    email_verification_code: Optional[str] = None
    email_verification_expires: Optional[datetime] = None
    signup_ip: Optional[str] = None
    signup_user_agent: Optional[str] = None
    refresh_token_hash: Optional[str] = None
    refresh_token_expires: Optional[datetime] = None
    is_suspended: Optional[bool] = None
    role: Optional[str] = None

    model_config = {"extra": "forbid"}
