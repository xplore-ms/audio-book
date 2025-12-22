from fastapi.middleware.cors import CORSMiddleware
from core.config import ALLOWED_ORIGIN

def setup_cors(app):
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[ALLOWED_ORIGIN],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
