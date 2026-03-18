from fastapi import Depends, HTTPException, Query, Request
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from app.db.mongo import users_collection_async

from app.core.config import settings

JWT_SECRET = settings.security.JWT_SECRET
JWT_ALGO = "HS256"


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


async def get_current_user(request: Request, token: str = Depends(oauth2_scheme)):
    final_token = request.cookies.get("access_token") or token
    if not final_token:
        raise HTTPException(401, "Not authenticated")

    try:
        payload = jwt.decode(final_token, JWT_SECRET, algorithms=[JWT_ALGO])
        email = payload.get("sub")
        if not email:
            raise HTTPException(401, "Invalid token")
    except JWTError:
        raise HTTPException(401, "Invalid token")

    user = await users_collection_async.find_one({"email": email})
    if not user:
        raise HTTPException(401, "User not found")

    return user


async def get_current_user_from_query(request: Request, token: str = Query(None)):
    """
    Dependency for getting user from query parameter (for media endpoints)
    Also supports falling back to 'access_token' cookie if query token is missing or 'None'.
    """
    final_token = (
        token if (token and token != "None") else request.cookies.get("access_token")
    )
    if not final_token:
        raise HTTPException(401, "Not authenticated")

    try:
        payload = jwt.decode(final_token, JWT_SECRET, algorithms=[JWT_ALGO])
        email = payload.get("sub")
        if not email:
            raise HTTPException(401, "Invalid token")
    except JWTError:
        raise HTTPException(401, "Invalid token")

    user = await users_collection_async.find_one({"email": email})
    if not user:
        raise HTTPException(401, "User not found")

    return user
