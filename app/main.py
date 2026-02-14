from fastapi import FastAPI
from app.core.cors import setup_cors
from app.api.v1.router import api_router
from app.db.mongo import ensure_indexes


app = FastAPI(title="Document → Audio API")


@app.on_event("startup")
async def startup_event():
	# ensure indexes (run sync index setup in thread to avoid blocking)
	import asyncio
	await asyncio.to_thread(ensure_indexes)

# CORS and middleware
setup_cors(app)

# Register consolidated API router
app.include_router(api_router)