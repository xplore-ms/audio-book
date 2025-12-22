import os
from dotenv import load_dotenv

load_dotenv()

ALLOWED_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
JWT_SECRET = os.getenv("JWT_SECRET", "token-secret-change-me")

SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "reading_app")
MAX_UPLOAD_SIZE = 50 * 1024 * 1024
MAX_PAGES = 4
