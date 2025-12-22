
from fastapi import APIRouter, HTTPException, Form
from mongo import users_collection
from core.security import (
    hash_password,
    verify_password,
    create_access_token
)
from datetime import datetime

router = APIRouter(prefix="/auth", tags=["Auth"])

@router.post("/register")
def register(
    email: str = Form(...),
    password: str = Form(...)
):
    if users_collection.find_one({"email": email}):
        raise HTTPException(400, "Email already registered")

    users_collection.insert_one({
        "email": email,
        "password_hash": hash_password(password),
        "credits": 10,  # 🎁 free starter credits
        "created_at": datetime.utcnow()
    })

    return {"message": "Account created successfully"}

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

    token = create_access_token(email)

    return {
        "access_token": token,
        "token_type": "bearer",
        "credits": user["credits"]
    }
