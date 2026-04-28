from __future__ import annotations

from datetime import datetime, UTC
from threading import Lock
from uuid import uuid4

from app.schemas.notification import UserNotificationResponse

OPERATIONS_RECIPIENT_ID = "__operations__"


class NotificationStore:
    def __init__(self, max_notifications_per_user: int = 100) -> None:
        self._notifications_by_user: dict[str, list[UserNotificationResponse]] = {}
        self._users_by_reservation: dict[str, set[str]] = {}
        self._lock = Lock()
        self._max_notifications_per_user = max_notifications_per_user

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

            reservation_id = str((payload or {}).get("reservation_id") or "").strip()
            if reservation_id:
                self._users_by_reservation.setdefault(reservation_id, set()).add(recipient_user_id)

        return notification

    def list_for_user(self, recipient_user_id: str) -> list[UserNotificationResponse]:
        with self._lock:
            return list(self._notifications_by_user.get(recipient_user_id, []))

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
                    updated_count += 1

        return updated_count

    def delete_for_reservation(self, *, reservation_id: str, exclude_types: list[str] | None = None) -> int:
        """
        Delete all notifications for a reservation, optionally excluding certain notification types.
        
        Args:
            reservation_id: The reservation ID to filter by
            exclude_types: List of notification types to NOT delete (e.g., ['reservation_cancelled_by_user'])
        
        Returns:
            Number of notifications deleted
        """
        deleted_count = 0
        exclude_types_set = set(exclude_types or [])

        with self._lock:
            recipient_ids = list(self._users_by_reservation.get(reservation_id, set()))
            still_has_notif: set[str] = set()
            for recipient_user_id in recipient_ids:
                bucket = self._notifications_by_user.get(recipient_user_id)
                if not bucket:
                    continue
                original_count = len(bucket)
                kept: list[UserNotificationResponse] = []
                for n in bucket:
                    is_target = (
                        n.payload
                        and n.payload.get("reservation_id") == reservation_id
                        and n.notification_type not in exclude_types_set
                    )
                    if is_target:
                        continue
                    kept.append(n)
                    if n.payload and n.payload.get("reservation_id") == reservation_id:
                        still_has_notif.add(recipient_user_id)
                self._notifications_by_user[recipient_user_id] = kept
                deleted_count += original_count - len(kept)

            if still_has_notif:
                self._users_by_reservation[reservation_id] = still_has_notif
            else:
                self._users_by_reservation.pop(reservation_id, None)

        return deleted_count


notification_store = NotificationStore()
