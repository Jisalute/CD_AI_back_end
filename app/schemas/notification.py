from pydantic import BaseModel
from typing import Optional, List, Any


class NotificationPush(BaseModel):
    title: str
    content: str
    target_user_id: Optional[str] = None
    target_username: Optional[str] = None


class NotificationItem(BaseModel):
    id: int
    user_id: Optional[str]
    username: Optional[str]
    title: str
    content: str
    target_user_id: Optional[str]
    target_username: Optional[str]
    operation_time: Optional[str]
    status: Optional[str]


class NotificationQueryResponse(BaseModel):
    items: List[NotificationItem]
    page: int
    page_size: int
    total: int
    total_pages: int
