from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta

from app.application.container import lab_reservation_repo, tutorial_session_repo
from app.core.datetime_utils import now_local_naive, parse_datetime
from app.notifications.store import notification_store
from app.realtime.manager import realtime_manager
from app.schemas.lab_reservation import LabReservationResponse
from app.schemas.tutorial_session import TutorialSessionResponse

CHECK_INTERVAL_SECONDS = 15
REMINDER_DISPATCH_WINDOW_SECONDS = CHECK_INTERVAL_SECONDS + 5
REMINDER_RULES = (
    ("24h", timedelta(hours=24)),
    ("30m", timedelta(minutes=30)),
)


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
        await self._tick(now=now or now_local_naive())

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            with contextlib.suppress(Exception):
                await self._tick(now=now_local_naive())
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=CHECK_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                continue

    async def _tick(self, now: datetime) -> None:
        self._prune_sent_reminders(now)

        with contextlib.suppress(Exception):
            completed_count = lab_reservation_repo.auto_complete_expired_reservations(now=now)
            if completed_count:
                await realtime_manager.broadcast(
                    {
                        "topic": "lab_reservation",
                        "action": "auto_completed",
                        "count": completed_count,
                        "at": now.isoformat(),
                    }
                )

        for reservation in lab_reservation_repo.list_all():
            await self._process_reservation(reservation, now)
        for tutorial_session in tutorial_session_repo.list_public():
            await self._process_tutorial_session(tutorial_session, now)

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

        for reminder_code, delta in REMINDER_RULES:
            if not self._should_dispatch_reminder(start_at=start_at, delta=delta, now=now):
                continue

            payload_match = {
                "reservation_id": reservation.id,
                "reminder_kind": reminder_code,
                "starts_at": reservation.start_at,
            }
            reminder_key = self._build_reminder_key(
                entity_type="reservation",
                entity_id=reservation.id,
                recipient_user_id=reservation.requested_by,
                reminder_code=reminder_code,
                starts_at=reservation.start_at,
            )

            if self._is_duplicate_reminder(
                reminder_key=reminder_key,
                recipient_user_id=reservation.requested_by,
                notification_type="reservation_reminder",
                payload_match=payload_match,
                start_at=start_at,
            ):
                continue

            title, message = self._build_reservation_copy(reminder_code)
            await self._create_and_broadcast_notification(
                recipient_user_id=reservation.requested_by,
                notification_type="reservation_reminder",
                title=title,
                message=message,
                payload={
                    **payload_match,
                    "purpose": reservation.purpose,
                    "laboratory_id": reservation.laboratory_id,
                    "laboratory_name": getattr(reservation, "laboratory_name", ""),
                    "status": reservation.status,
                    "target_path": "/app/reservas/nueva",
                },
                reminder_key=reminder_key,
                start_at=start_at,
            )

    async def _process_tutorial_session(self, tutorial_session: TutorialSessionResponse, now: datetime) -> None:
        if not tutorial_session.is_published or not tutorial_session.enrolled_students:
            return

        try:
            start_at = parse_datetime(tutorial_session.start_at)
        except ValueError:
            return

        if start_at <= now:
            return

        for reminder_code, delta in REMINDER_RULES:
            if not self._should_dispatch_reminder(start_at=start_at, delta=delta, now=now):
                continue

            title, message = self._build_tutorial_copy(reminder_code)
            for enrollment in tutorial_session.enrolled_students:
                recipient_user_id = str(enrollment.student_id or "").strip()
                if not recipient_user_id:
                    continue

                payload_match = {
                    "tutorial_session_id": tutorial_session.id,
                    "reminder_kind": reminder_code,
                    "starts_at": tutorial_session.start_at,
                }
                reminder_key = self._build_reminder_key(
                    entity_type="tutorial",
                    entity_id=tutorial_session.id,
                    recipient_user_id=recipient_user_id,
                    reminder_code=reminder_code,
                    starts_at=tutorial_session.start_at,
                )

                if self._is_duplicate_reminder(
                    reminder_key=reminder_key,
                    recipient_user_id=recipient_user_id,
                    notification_type="tutorial_reminder",
                    payload_match=payload_match,
                    start_at=start_at,
                ):
                    continue

                await self._create_and_broadcast_notification(
                    recipient_user_id=recipient_user_id,
                    notification_type="tutorial_reminder",
                    title=title,
                    message=message,
                    payload={
                        **payload_match,
                        "topic": tutorial_session.topic,
                        "session_date": tutorial_session.session_date,
                        "start_time": tutorial_session.start_time,
                        "end_time": tutorial_session.end_time,
                        "location": tutorial_session.location,
                        "laboratory_id": tutorial_session.laboratory_id,
                        "tutor_name": tutorial_session.tutor_name,
                        "target_path": "/app/tutorias",
                    },
                    reminder_key=reminder_key,
                    start_at=start_at,
                )

    def _build_reminder_key(
        self,
        *,
        entity_type: str,
        entity_id: str,
        recipient_user_id: str,
        reminder_code: str,
        starts_at: str,
    ) -> str:
        return f"{entity_type}:{entity_id}:{recipient_user_id}:{reminder_code}:{starts_at}"

    def _should_dispatch_reminder(self, *, start_at: datetime, delta: timedelta, now: datetime) -> bool:
        reminder_at = start_at - delta
        dispatch_window_end = reminder_at + timedelta(seconds=REMINDER_DISPATCH_WINDOW_SECONDS)
        return reminder_at <= now < dispatch_window_end

    def _is_duplicate_reminder(
        self,
        *,
        reminder_key: str,
        recipient_user_id: str,
        notification_type: str,
        payload_match: dict,
        start_at: datetime,
    ) -> bool:
        if reminder_key in self._sent_reminders:
            return True

        if notification_store.exists_for_user(
            recipient_user_id=recipient_user_id,
            notification_type=notification_type,
            payload_match=payload_match,
        ):
            self._sent_reminders[reminder_key] = start_at
            return True

        return False

    async def _create_and_broadcast_notification(
        self,
        *,
        recipient_user_id: str,
        notification_type: str,
        title: str,
        message: str,
        payload: dict,
        reminder_key: str,
        start_at: datetime,
    ) -> None:
        notification = notification_store.create(
            recipient_user_id=recipient_user_id,
            notification_type=notification_type,
            title=title,
            message=message,
            payload=payload,
        )
        self._sent_reminders[reminder_key] = start_at

        await realtime_manager.broadcast(
            {
                "topic": "user_notification",
                "action": "create",
                "recipients": [recipient_user_id],
                "record": notification.model_dump(),
                "at": datetime.utcnow().isoformat(),
            }
        )

    def _build_reservation_copy(self, reminder_code: str) -> tuple[str, str]:
        if reminder_code == "30m":
            return "Recordatorio Cercano", "Tu reserva aprobada comienza en 30 minutos."
        return "Recordatorio de Reserva", "Tu reserva aprobada comienza en 24 horas."

    def _build_tutorial_copy(self, reminder_code: str) -> tuple[str, str]:
        if reminder_code == "30m":
            return "Tutoria por Comenzar", "Tu tutoria inscrita comienza en 30 minutos."
        return "Recordatorio de Tutoria", "Tu tutoria inscrita comienza en 24 horas."


reservation_reminder_scheduler = ReservationReminderScheduler()
