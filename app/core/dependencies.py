from fastapi import Depends, HTTPException, Query
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
import os
from  app.db.mongo import users_collection

from app.core import config

JWT_SECRET = config.JWT_SECRET
JWT_ALGO = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        email = payload.get("sub")
        if not email:
            raise HTTPException(401, "Invalid token")
    except JWTError:
        raise HTTPException(401, "Invalid token")

    user = users_collection.find_one({"email": email})
    if not user:
        raise HTTPException(401, "User not found")

    return user

def get_current_user_from_query(token: str = Query(...)):
    """
    Dependency for getting user from query parameter (for media endpoints)
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        email = payload.get("sub")
        if not email:
            raise HTTPException(401, "Invalid token")
    except JWTError:
        raise HTTPException(401, "Invalid token")

    user = users_collection.find_one({"email": email})
    if not user:
        raise HTTPException(401, "User not found")

    return user
