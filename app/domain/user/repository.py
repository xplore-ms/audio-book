from typing import Any, Dict, Optional
from bson import ObjectId
from app.domain.user.schemas import UserInDB


class UserRepository:
    def __init__(self, collection):
        self.collection = collection

    async def find_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one({"email": email})

    async def find_by_filter(
        self, filter_q: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one(filter_q)

    async def insert(self, user: UserInDB) -> Any:
        doc = user.model_dump()
        return await self.collection.insert_one(doc)

    async def update_by_id(self, user_id, update: Dict[str, Any]) -> Any:
        # Prevent NoSQL injection by ensuring user_id is not a query object
        if isinstance(user_id, dict):
            raise ValueError("Invalid user_id format")

        if isinstance(user_id, str):
            try:
                user_id = ObjectId(user_id)
            except Exception:
                pass

        # Ensure at least one MongoDB operator is used to prevent accidental document replacement
        if not any(k.startswith("$") for k in update.keys()):
            raise ValueError("Update must use MongoDB operators ($set, $unset, etc.)")

        return await self.collection.update_one({"_id": user_id}, update)
