from fastapi import FastAPI
from core.cors import setup_cors

from auth.router import router as auth_router
from jobs.router import router as jobs_router
from audio.router import router as audio_router
from credits.router import router as credits_router
from health.router import router as health_router

from mongo import ensure_indexes

ensure_indexes()

app = FastAPI(title="Document → Audio API")

setup_cors(app)


app.include_router(auth_router)
app.include_router(credits_router)
app.include_router(jobs_router)
app.include_router(audio_router)
app.include_router(health_router)