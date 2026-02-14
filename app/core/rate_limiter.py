import os
import redis
from fastapi import HTTPException
from dotenv import load_dotenv
load_dotenv()

from app.core import config

REDIS_URL = config.REDIS_BROKER

redis_client = redis.from_url(
    REDIS_URL,
    decode_responses=True
)

def rate_limit(key: str, limit: int, window_seconds: int):
    key = f"rl:{key}"

    current = redis_client.incr(key)

    if current == 1:
        redis_client.expire(key, window_seconds)

    if current > limit:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please slow down."
        )
