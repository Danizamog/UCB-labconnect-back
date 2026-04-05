from fastapi import APIRouter, Depends, HTTPException, status

from app.core.dependencies import get_current_user
from app.notifications.store import OPERATIONS_RECIPIENT_ID, notification_store
from app.schemas.notification import MarkAllNotificationsReadResponse, UserNotificationResponse

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _notification_buckets_for_user(current_user: dict) -> list[str]:
    recipient_user_id = str(current_user.get("user_id") or "").strip()
    if not recipient_user_id:
        return []

    buckets = [recipient_user_id]
    permissions = set(current_user.get("permissions") or [])
    if (
        current_user.get("role") == "admin"
        or "*" in permissions
        or permissions.intersection({"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"})
    ):
        buckets.append(OPERATIONS_RECIPIENT_ID)

    return buckets


@router.get("/mine", response_model=list[UserNotificationResponse])
def list_my_notifications(current_user: dict = Depends(get_current_user)) -> list[UserNotificationResponse]:
    buckets = _notification_buckets_for_user(current_user)
    if not buckets:
        return []

    notifications: list[UserNotificationResponse] = []
    seen_ids: set[str] = set()
    for bucket in buckets:
        for notification in notification_store.list_for_user(bucket):
            if notification.id in seen_ids:
                continue
            seen_ids.add(notification.id)
            notifications.append(notification)

    return sorted(notifications, key=lambda item: item.created_at, reverse=True)


@router.patch("/{notification_id}/read", response_model=UserNotificationResponse)
@router.put("/{notification_id}/read", response_model=UserNotificationResponse)
def mark_notification_as_read(
    notification_id: str,
    current_user: dict = Depends(get_current_user),
) -> UserNotificationResponse:
    buckets = _notification_buckets_for_user(current_user)
    if not buckets:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notificacion no encontrada")

    notification = notification_store.mark_as_read_for_any(
        recipient_user_ids=buckets,
        notification_id=notification_id,
    )
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notificacion no encontrada")
    return notification


@router.put("/read-all", response_model=MarkAllNotificationsReadResponse)
def mark_all_notifications_as_read(
    current_user: dict = Depends(get_current_user),
) -> MarkAllNotificationsReadResponse:
    buckets = _notification_buckets_for_user(current_user)
    if not buckets:
        return MarkAllNotificationsReadResponse(updated_count=0)

    updated_count = notification_store.mark_all_as_read_for_many(recipient_user_ids=buckets)
    return MarkAllNotificationsReadResponse(updated_count=updated_count)
