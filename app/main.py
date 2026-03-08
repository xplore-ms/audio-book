from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.gzip import GZipMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
import asyncio
import logging

from app.core.cors import setup_cors
from app.api.v1.router import api_router
from app.db.mongo import ensure_indexes

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure MongoDB indexes are created
    await asyncio.to_thread(ensure_indexes)
    yield
    # Shutdown: (add cleanup here if needed in future)


app = FastAPI(title="Document → Audio API", lifespan=lifespan)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "message": str(exc)},
    )


# CORS and middleware
setup_cors(app)
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Register consolidated API router
app.include_router(api_router)
