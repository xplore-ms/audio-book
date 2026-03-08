from fastapi.middleware.cors import CORSMiddleware
# from app.core.config import ALLOWED_ORIGIN


def setup_cors(app):
    # Handle multiple origins if provided as comma-separated string
    # Normalize by stripping trailing slashes as per CORS standards
    # origins = (
    #     [o.strip().rstrip("/") for o in ALLOWED_ORIGIN.split(",")]
    #     if ALLOWED_ORIGIN
    #     else ["*"]
    # )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://audio-book-frontend.vercel.app"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
