from datetime import datetime
from fastapi import APIRouter, HTTPException, Form, Request
from fastapi.params import Depends
from app.core.rate_limiter import rate_limit
from app.core.dependencies import get_current_user
from app.domain.user import service as user_service
import logging


router = APIRouter(prefix="/auth", tags=["Auth"])

# Set up logging safely
logger = logging.getLogger("auth")
logger.setLevel(logging.INFO)


def get_client_ip(request: Request):
    if request.headers.get("x-forwarded-for"):
        return request.headers["x-forwarded-for"].split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


@router.post("/register")
async def register(request: Request, email: str = Form(...), password: str = Form(...), device_fingerprint_hash: str = Form(...)):
    ip_address = get_client_ip(request)
    rate_limit(f"register:{email}", limit=5, window_seconds=300)
    if ip_address:
        rate_limit(f"register_ip:{ip_address}", limit=10, window_seconds=300)

    user_agent = request.headers.get("user-agent")

    svc = user_service.UserService.default()
    try:
        user_in = user_service.UserCreate(email=email, password=password, device_fingerprint_hash=device_fingerprint_hash)
        return await svc.register_user(user_in, ip_address, user_agent)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/verify-email-code")
async def verify_email_code(email: str = Form(...), code: str = Form(...)):
    rate_limit(f"verify-email:{email}", limit=5, window_seconds=300)
    svc = user_service.UserService.default()
    try:
        return await svc.verify_email_code(email, code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...)):
    ip_address = get_client_ip(request)
    rate_limit(f"login:{email}", limit=5, window_seconds=300)
    if ip_address:
        rate_limit(f"login_ip:{ip_address}", limit=20, window_seconds=300)

    svc = user_service.UserService.default()
    try:
        return await svc.login_user(email, password)
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.post("/forgot-password")
async def forgot_password(request: Request, email: str = Form(...)):
    ip_address = get_client_ip(request)
    rate_limit(f"forgot-password:{email}", limit=3, window_seconds=3600)
    if ip_address:
        rate_limit(f"forgot-password_ip:{ip_address}", limit=10, window_seconds=3600)

    svc = user_service.UserService.default()
    return await svc.forgot_password(email)


@router.post("/reset-password")
async def reset_password(email: str = Form(...), code: str = Form(...), new_password: str = Form(...)):
    rate_limit(f"reset-password:{email}", limit=5, window_seconds=300)
    svc = user_service.UserService.default()
    try:
        return await svc.reset_password(email, code, new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/me")
async def get_me(user=Depends(get_current_user)):
    svc = user_service.UserService.default()
    return await svc.get_me(user)
