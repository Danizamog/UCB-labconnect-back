from __future__ import annotations

from pydantic import BaseModel, Field


class UserNotificationResponse(BaseModel):
    id: str
    recipient_user_id: str
    notification_type: str
    title: str
    message: str
    payload: dict = Field(default_factory=dict)
    is_read: bool = False
    created_at: str


class MarkAllNotificationsReadResponse(BaseModel):
    updated_count: int
