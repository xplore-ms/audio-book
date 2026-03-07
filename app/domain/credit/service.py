from datetime import datetime, date
from fastapi import HTTPException
from app.db.mongo import users_collection


UPLOAD_COST = 10
DOWNLOAD_COST = 20
PAGE_COST = 1

DAILY_LOGIN_REWARD = 5
TWITTER_REWARD = 10


def get_user(user_id: str):
    user = users_collection.find_one({"_id": user_id})
    if not user:
        raise HTTPException(401, "User not found")
    return user


def require_credits(user, amount: int):
    if user["credits"] < amount:
        raise HTTPException(403, "Insufficient credits")


def deduct_credits_atomic(user_id, amount):
    # 1. Atomic decrement of total credits
    result = users_collection.update_one(
        {"_id": user_id, "credits": {"$gte": amount}}, {"$inc": {"credits": -amount}}
    )

    if result.modified_count == 0:
        raise HTTPException(403, "Insufficient credits")

    # 2. Update batches (FIFO)
    user = users_collection.find_one({"_id": user_id})
    if not user:
        return

    batches = user.get("credit_batches", [])
    if not batches:
        return

    remaining_to_deduct = amount

    # Sort by expires_at (expiring soonest first, non-expiring last)
    def sort_key(b):
        exp = b.get("expires_at")
        if exp is None:
            return datetime.max
        return exp

    sorted_batches = sorted(batches, key=sort_key)

    for batch in sorted_batches:
        current_remaining = batch.get("remaining_credits", 0)
        if batch.get("status") != "inactive" and current_remaining > 0:
            deduct = min(current_remaining, remaining_to_deduct)
            batch["remaining_credits"] = current_remaining - deduct
            remaining_to_deduct -= deduct
            if remaining_to_deduct <= 0:
                break

    # Update the user document with updated batches
    users_collection.update_one(
        {"_id": user_id}, {"$set": {"credit_batches": sorted_batches}}
    )


def add_credits(user_id: str, amount: int):
    users_collection.update_one({"_id": user_id}, {"$inc": {"credits": amount}})


def reward_daily_login(user):
    today = date.today()

    last_login = user.get("last_login")
    if last_login and last_login.date() == today:
        return False

    users_collection.update_one(
        {"id": user["id"]},
        {
            "$set": {"last_login": datetime.utcnow()},
            "$inc": {"credits": DAILY_LOGIN_REWARD},
        },
    )
    return True


def reward_twitter_follow(user):
    if user["tasks"].get("twitter_follow"):
        raise HTTPException(400, "Task already completed")

    users_collection.update_one(
        {"id": user["id"]},
        {"$set": {"tasks.twitter_follow": True}, "$inc": {"credits": TWITTER_REWARD}},
    )
