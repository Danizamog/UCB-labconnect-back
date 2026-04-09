from __future__ import annotations

from datetime import datetime, UTC
from threading import Lock
from uuid import uuid4

from pydantic import ValidationError

from app.infrastructure.local_store import LocalJsonStore
from app.schemas.notification import UserNotificationResponse

OPERATIONS_RECIPIENT_ID = "__operations__"


class NotificationStore:
    def __init__(self, max_notifications_per_user: int = 100) -> None:
        self._notifications_by_user: dict[str, list[UserNotificationResponse]] = {}
        self._lock = Lock()
        self._max_notifications_per_user = max_notifications_per_user
        self._local_store = LocalJsonStore("user_notification")
        self._load_from_local_store()

    def _load_from_local_store(self) -> None:
        loaded: dict[str, list[UserNotificationResponse]] = {}
        for raw_record in self._local_store.list():
            try:
                notification = UserNotificationResponse.model_validate(raw_record)
            except ValidationError:
                continue
            loaded.setdefault(notification.recipient_user_id, []).append(notification)

        for bucket in loaded.values():
            bucket.sort(key=lambda item: item.created_at, reverse=True)

        with self._lock:
            self._notifications_by_user = loaded

    def _persist(self, notification: UserNotificationResponse, *, operation: str = "update") -> None:
        self._local_store.upsert(notification.id, notification.model_dump(), operation=operation)

    def create(
        self,
        *,
        recipient_user_id: str,
        notification_type: str,
        title: str,
        message: str,
        payload: dict | None = None,
    ) -> UserNotificationResponse:
        notification = UserNotificationResponse(
            id=str(uuid4()),
            recipient_user_id=recipient_user_id,
            notification_type=notification_type,
            title=title,
            message=message,
            payload=payload or {},
            is_read=False,
            created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )

        with self._lock:
            bucket = self._notifications_by_user.setdefault(recipient_user_id, [])
            bucket.insert(0, notification)
            if len(bucket) > self._max_notifications_per_user:
                del bucket[self._max_notifications_per_user :]

        self._persist(notification, operation="create")
        return notification

    def list_for_user(self, recipient_user_id: str) -> list[UserNotificationResponse]:
        with self._lock:
            return list(self._notifications_by_user.get(recipient_user_id, []))

    def exists_for_user(
        self,
        *,
        recipient_user_id: str,
        notification_type: str,
        payload_match: dict | None = None,
    ) -> bool:
        expected_payload = payload_match or {}

        with self._lock:
            bucket = self._notifications_by_user.get(recipient_user_id, [])
            for notification in bucket:
                if notification.notification_type != notification_type:
                    continue

                payload = notification.payload if isinstance(notification.payload, dict) else {}
                if all(payload.get(key) == value for key, value in expected_payload.items()):
                    return True

        return False

    def mark_as_read(
        self,
        *,
        recipient_user_id: str,
        notification_id: str,
    ) -> UserNotificationResponse | None:
        with self._lock:
            bucket = self._notifications_by_user.get(recipient_user_id, [])
            for index, notification in enumerate(bucket):
                if notification.id != notification_id:
                    continue

                updated_notification = notification.model_copy(update={"is_read": True})
                bucket[index] = updated_notification
                self._persist(updated_notification)
                return updated_notification

        return None

    def mark_as_read_for_any(
        self,
        *,
        recipient_user_ids: list[str],
        notification_id: str,
    ) -> UserNotificationResponse | None:
        with self._lock:
            for recipient_user_id in recipient_user_ids:
                bucket = self._notifications_by_user.get(recipient_user_id, [])
                for index, notification in enumerate(bucket):
                    if notification.id != notification_id:
                        continue

                    updated_notification = notification.model_copy(update={"is_read": True})
                    bucket[index] = updated_notification
                    self._persist(updated_notification)
                    return updated_notification

        return None

    def mark_all_as_read(self, *, recipient_user_id: str) -> int:
        updated_count = 0

        with self._lock:
            bucket = self._notifications_by_user.get(recipient_user_id, [])
            for index, notification in enumerate(bucket):
                if notification.is_read:
                    continue

                bucket[index] = notification.model_copy(update={"is_read": True})
                self._persist(bucket[index])
                updated_count += 1

        return updated_count

    def mark_all_as_read_for_many(self, *, recipient_user_ids: list[str]) -> int:
        updated_count = 0

        with self._lock:
            for recipient_user_id in recipient_user_ids:
                bucket = self._notifications_by_user.get(recipient_user_id, [])
                for index, notification in enumerate(bucket):
                    if notification.is_read:
                        continue

                    bucket[index] = notification.model_copy(update={"is_read": True})
                    self._persist(bucket[index])
                    updated_count += 1

        return updated_count


notification_store = NotificationStore()
