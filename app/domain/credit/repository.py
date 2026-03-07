from typing import Any, Dict
from app.db.mongo import users_collection


def get_user_credits(user_id: str) -> int:
    u = users_collection.find_one({"_id": user_id})
    return u.get("credits", 0) if u else 0


def deduct_credits_atomic(user_id: str, amount: int):
    return users_collection.update_one(
        {"_id": user_id, "credits": {"$gte": amount}}, {"$inc": {"credits": -amount}}
    )


def require_credits(user: Dict[str, Any], amount: int):
    if user.get("credits", 0) < amount:
        raise ValueError("Insufficient credits")
