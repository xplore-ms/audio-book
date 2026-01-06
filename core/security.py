import os
import hashlib
import hmac
import base64
from datetime import datetime, timedelta
from jose import jwt

JWT_SECRET = os.getenv("JWT_SECRET", "token-secret-change-me")
JWT_ALGO = "HS256"

# Password hashing config
HASH_ITERATIONS = 120_000
SALT_SIZE = 16

ACCESS_TOKEN_HOURS = 24
REFRESH_TOKEN_DAYS = 30

def hash_password(password: str) -> str:
    """
    Node.js–style password hashing using PBKDF2.
    Fast, non-blocking, no external libs.
    """
    salt = os.urandom(SALT_SIZE)

    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        HASH_ITERATIONS
    )

    return base64.b64encode(salt + key).decode("utf-8")


def verify_password(password: str, stored_hash: str) -> bool:
    decoded = base64.b64decode(stored_hash.encode("utf-8"))

    salt = decoded[:SALT_SIZE]
    stored_key = decoded[SALT_SIZE:]

    new_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        HASH_ITERATIONS
    )

    return hmac.compare_digest(new_key, stored_key)


def create_access_token(email: str) -> str:
    payload = {
        "sub": email,
        "type": "access",
        "exp": datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_HOURS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

def create_refresh_token(email: str) -> str:
    payload = {
        "sub": email,
        "type": "refresh",
        "exp": datetime.utcnow() + timedelta(days=REFRESH_TOKEN_DAYS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
