from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.credits import router as credits_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.audio import router as audio_router
from app.api.v1.health import router as health_router
from app.api.v1.paystack import router as payments_router
from app.api.v1.voice import router as voice_router
from app.api.v1.admin import router as admin_router
from app.api.v1.public_audio import public_router as admin_public_router


api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth_router)
api_router.include_router(credits_router)
api_router.include_router(jobs_router)
api_router.include_router(audio_router)
api_router.include_router(health_router)
api_router.include_router(payments_router)
api_router.include_router(voice_router)
api_router.include_router(admin_router)
api_router.include_router(admin_public_router)
