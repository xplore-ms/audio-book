from typing import Any, Dict, Optional
from app.domain.user.schemas import UserInDB


class UserRepository:
    def __init__(self, collection):
        self.collection = collection

    async def find_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one({"email": email})

    async def find_by_filter(self, filter_q: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one(filter_q)

    async def insert(self, user: UserInDB) -> Any:
        doc = user.model_dump()
        return await self.collection.insert_one(doc)

    async def update_by_id(self, user_id, update: Dict[str, Any]) -> Any:
        return await self.collection.update_one({"_id": user_id}, update)

