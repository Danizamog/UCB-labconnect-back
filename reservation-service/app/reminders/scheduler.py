from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta

from app.application.container import lab_reservation_repo
from app.core.config import settings
from app.core.datetime_utils import parse_datetime
from app.notifications.store import notification_store
from app.realtime.manager import realtime_manager
from app.schemas.lab_reservation import LabReservationResponse

CHECK_INTERVAL_SECONDS = settings.reservation_reminder_check_interval_seconds
REMINDER_RULES = (
    ("24h", timedelta(hours=24), "Recordatorio de Reserva", "Tu reserva aprobada comienza en 24 horas."),
    ("30m", timedelta(minutes=30), "Recordatorio Cercano", "Tu reserva aprobada comienza en 30 minutos."),
)
MAX_REMINDER_WINDOW = max(delta for _, delta, _, _ in REMINDER_RULES)


class ReservationReminderScheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._sent_reminders: dict[str, datetime] = {}

    def start(self) -> None:
        if self._task and not self._task.done():
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="reservation-reminder-scheduler")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is None:
            return

        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def run_once(self, now: datetime | None = None) -> None:
        await self._tick(now=now or datetime.utcnow())

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            with contextlib.suppress(Exception):
                await self._tick(now=datetime.utcnow())
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=CHECK_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                continue

    async def _tick(self, now: datetime) -> None:
        self._prune_sent_reminders(now)

        window_start = now.isoformat()
        window_end = (now + MAX_REMINDER_WINDOW).isoformat()
        candidates = await asyncio.to_thread(
            lab_reservation_repo.list_active_approved_with_start_before,
            start_before=window_end,
            start_after=window_start,
        )

        for reservation in candidates:
            await self._process_reservation(reservation, now)

    def _prune_sent_reminders(self, now: datetime) -> None:
        expired_keys = [key for key, start_at in self._sent_reminders.items() if start_at <= now]
        for key in expired_keys:
            self._sent_reminders.pop(key, None)

    async def _process_reservation(self, reservation: LabReservationResponse, now: datetime) -> None:
        if reservation.status != "approved" or not reservation.is_active or not reservation.requested_by:
            return

        try:
            start_at = parse_datetime(reservation.start_at)
        except ValueError:
            return

        if start_at <= now:
            return

        for reminder_code, delta, title, message in REMINDER_RULES:
            reminder_at = start_at - delta
            reminder_key = f"{reservation.id}:{reminder_code}:{reservation.start_at}"

            if reminder_key in self._sent_reminders:
                continue

            if now < reminder_at:
                continue

            notification = await asyncio.to_thread(
                notification_store.create,
                recipient_user_id=reservation.requested_by,
                notification_type="reservation_reminder",
                title=title,
                message=message,
                payload={
                    "reservation_id": reservation.id,
                    "purpose": reservation.purpose,
                    "starts_at": reservation.start_at,
                    "laboratory_id": reservation.laboratory_id,
                    "status": reservation.status,
                    "reminder_kind": reminder_code,
                },
            )

            self._sent_reminders[reminder_key] = start_at

            await realtime_manager.broadcast(
                {
                    "topic": "user_notification",
                    "action": "create",
                    "recipients": [reservation.requested_by],
                    "record": notification.model_dump(),
                    "at": datetime.utcnow().isoformat(),
                }
            )


reservation_reminder_scheduler = ReservationReminderScheduler()
