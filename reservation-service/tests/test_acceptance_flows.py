from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.api.v1.endpoints import availability as availability_endpoints
from app.api.v1.endpoints import notifications as notification_endpoints
from app.api.v1.endpoints import reservations as reservation_endpoints
from app.core.config import settings
from app.reminders import scheduler as reminder_scheduler
from app.infrastructure.repositories.tutorial_session_repository import TutorialSessionRepository
from app.schemas.lab_reservation import LabReservationResponse
from app.schemas.notification import UserNotificationResponse
from app.schemas.tutorial_session import TutorialSessionCreate


def _future_range(days: int = 2, start_hour: int = 10, duration_hours: int = 1) -> tuple[str, str, str]:
    base = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=days)
    start = base.replace(hour=start_hour)
    end = start + timedelta(hours=duration_hours)
    return start.isoformat(), end.isoformat(), start.date().isoformat()


def _reservation(*, reservation_id: str = "res-1", status: str = "approved", requested_by: str = "student-1") -> LabReservationResponse:
    start_at, end_at, _ = _future_range()
    created = datetime.now().isoformat()
    return LabReservationResponse(
        id=reservation_id,
        laboratory_id="lab-1",
        area_id="area-1",
        requested_by=requested_by,
        purpose="Practica de laboratorio",
        start_at=start_at,
        end_at=end_at,
        status=status,
        attendees_count=1,
        notes="",
        approved_by="admin-1" if status == "approved" else "",
        approved_at=created if status == "approved" else "",
        cancel_reason="",
        is_active=status not in {"cancelled", "completed", "absent", "rejected"},
        created=created,
        updated=created,
        requested_by_name="Student One",
        requested_by_email="student1@ucb.edu.bo",
        station_label="",
        check_in_at="",
        check_out_at="",
        is_walk_in=False,
    )


class _FakeRealtimeManager:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def broadcast(self, payload: dict) -> None:
        self.events.append(payload)


class _FakeReservationRepo:
    def __init__(self, reservation: LabReservationResponse) -> None:
        self.current = reservation
        self.cancel_calls: list[str] = []

    def get_by_id(self, reservation_id: str) -> LabReservationResponse | None:
        if self.current.id != reservation_id:
            return None
        return self.current

    def cancel(self, reservation_id: str) -> LabReservationResponse | None:
        if self.current.id != reservation_id:
            return None
        self.cancel_calls.append(reservation_id)
        self.current = self.current.model_copy(update={"status": "cancelled", "is_active": False})
        return self.current


class _FakeReservationUpdateRepo:
    def __init__(self, reservation: LabReservationResponse) -> None:
        self.current = reservation
        self.update_payloads: list[dict] = []

    def get_by_id(self, reservation_id: str) -> LabReservationResponse | None:
        if self.current.id != reservation_id:
            return None
        return self.current

    def update(self, reservation_id: str, body):
        if self.current.id != reservation_id:
            return None
        payload = {key: value for key, value in body.model_dump().items() if value is not None}
        self.update_payloads.append(payload)
        self.current = self.current.model_copy(update=payload)
        return self.current


class _FakeListRepo:
    def __init__(self, items: list) -> None:
        self._items = items

    def list_all(self):
        return list(self._items)


class _FakeLaboratoryAccessRepo:
    def __init__(self, records: dict[str, dict] | None = None) -> None:
        self._records = records or {}

    def get_by_id(self, laboratory_id: str) -> dict | None:
        return self._records.get(laboratory_id)


class _FakeNotificationStore:
    def __init__(self) -> None:
        self.created: list[dict] = []

    def create(self, **kwargs):
        self.created.append(kwargs)
        return type("_Notification", (), {"model_dump": lambda self: kwargs})()


class _FakePublicTutorialRepo:
    def list_public(self):
        return []


class _FakeReservationSource:
    def __init__(self, reservations: list[LabReservationResponse]) -> None:
        self._reservations = reservations

    def list_all(self):
        return list(self._reservations)


class ReservationCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_user_cancel_keeps_record_and_notifies_operations_for_approved_reservation(self) -> None:
        repo = _FakeReservationRepo(_reservation(status="approved"))
        realtime = _FakeRealtimeManager()
        notifications: list[tuple[str, str]] = []

        async def _fake_notify(reservation, current_user):
            notifications.append((reservation.id, current_user.get("user_id") or ""))

        current_user = {"user_id": "student-1", "permissions": [], "role": "student", "name": "Student One"}

        with patch.object(reservation_endpoints, "lab_reservation_repo", repo), \
             patch.object(reservation_endpoints, "realtime_manager", realtime), \
             patch.object(reservation_endpoints, "_notify_operations_reservation_cancelled", _fake_notify):
            response = await reservation_endpoints.delete_reservation("res-1", current_user=current_user)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(repo.cancel_calls, ["res-1"])
        self.assertEqual(notifications, [("res-1", "student-1")])
        self.assertEqual(len(realtime.events), 1)
        self.assertEqual(realtime.events[0]["action"], "update")
        self.assertEqual(realtime.events[0]["record"]["status"], "cancelled")
        self.assertFalse(realtime.events[0]["record"]["is_active"])

    async def test_pending_cancellation_does_not_notify_operations(self) -> None:
        repo = _FakeReservationRepo(_reservation(status="pending", reservation_id="res-2"))
        realtime = _FakeRealtimeManager()
        notifications: list[str] = []

        async def _fake_notify(reservation, current_user):
            notifications.append(reservation.id)

        current_user = {"user_id": "student-1", "permissions": [], "role": "student", "name": "Student One"}

        with patch.object(reservation_endpoints, "lab_reservation_repo", repo), \
             patch.object(reservation_endpoints, "realtime_manager", realtime), \
             patch.object(reservation_endpoints, "_notify_operations_reservation_cancelled", _fake_notify):
            await reservation_endpoints.delete_reservation("res-2", current_user=current_user)

        self.assertEqual(notifications, [])
        self.assertEqual(realtime.events[0]["record"]["status"], "cancelled")


class ReservationModificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_user_can_modify_approved_reservation_only_once_and_it_stays_approved(self) -> None:
        reservation = _reservation(status="approved", reservation_id="res-3").model_copy(
            update={"user_modification_count": 0},
        )
        repo = _FakeReservationUpdateRepo(reservation)
        realtime = _FakeRealtimeManager()
        current_user = {"user_id": "student-1", "permissions": [], "role": "student", "name": "Student One"}

        body = reservation_endpoints.LabReservationUpdate(
            laboratory_id="lab-2",
            area_id="area-2",
            start_at=reservation.start_at.replace("10:00:00", "11:00:00"),
            end_at=reservation.end_at.replace("11:00:00", "12:00:00"),
        )

        with patch.object(reservation_endpoints, "lab_reservation_repo", repo), \
             patch.object(reservation_endpoints, "realtime_manager", realtime), \
             patch.object(reservation_endpoints, "ensure_user_can_reserve_laboratory", lambda *args, **kwargs: None), \
             patch.object(reservation_endpoints, "_validate_reservation_time_rules", lambda *args, **kwargs: None):
            updated = await reservation_endpoints.update_reservation("res-3", body, current_user=current_user)

            self.assertEqual(updated.status, "approved")
            self.assertEqual(updated.user_modification_count, 1)
            self.assertEqual(repo.update_payloads[-1]["user_modification_count"], 1)

            with self.assertRaisesRegex(Exception, "Solo puedes modificar una reserva una vez"):
                await reservation_endpoints.update_reservation("res-3", body, current_user=current_user)


class AvailabilityAfterCancellationTests(unittest.TestCase):
    def test_cancelled_reservation_releases_public_slot(self) -> None:
        start_at, end_at, day = _future_range(days=3, start_hour=9)
        cancelled_reservation = _reservation(status="cancelled")
        cancelled_reservation = cancelled_reservation.model_copy(
            update={"start_at": start_at, "end_at": end_at, "is_active": False},
        )

        current_user = {"user_id": "student-1", "permissions": [], "role": "student"}
        fake_now = datetime.fromisoformat(start_at) - timedelta(days=1)

        with patch.object(availability_endpoints, "ensure_user_can_reserve_laboratory", lambda *args, **kwargs: None), \
             patch.object(availability_endpoints, "lab_schedule_repo", _FakeListRepo([])), \
             patch.object(availability_endpoints, "lab_block_repo", _FakeListRepo([])), \
             patch.object(availability_endpoints, "lab_reservation_repo", _FakeReservationSource([cancelled_reservation])), \
             patch.object(availability_endpoints, "tutorial_session_repo", _FakePublicTutorialRepo()), \
             patch.object(availability_endpoints, "now_local_naive", lambda: fake_now):
            response = availability_endpoints.get_lab_availability("lab-1", day=day, current_user=current_user)

        slot = next(item for item in response.slots if item.start_time == "09:00" and item.end_time == "10:00")
        self.assertEqual(slot.state, "available")


class _StubReservationRepo:
    def __init__(self, reservations: list[LabReservationResponse] | None = None) -> None:
        self._reservations = reservations or []

    def list_all(self) -> list[LabReservationResponse]:
        return list(self._reservations)


class TutorialAcceptanceTests(unittest.TestCase):
    def test_student_enrollment_and_cancellation_update_capacity_and_personal_listing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            storage_path = Path(temp_dir) / "tutorial_sessions.json"
            with patch.object(settings, "tutorial_sessions_storage_path", str(storage_path)):
                repo = TutorialSessionRepository(_StubReservationRepo())
                _, _, session_day = _future_range(days=4, start_hour=11)
                session = repo.create(
                    TutorialSessionCreate(
                        topic="Tutoria de Algebra",
                        description="Repaso para el parcial",
                        laboratory_id="lab-1",
                        location="Laboratorio 101",
                        session_date=session_day,
                        start_time="11:00",
                        end_time="12:00",
                        max_students=2,
                        tutor_id="tutor-1",
                        tutor_name="Tutor Uno",
                        tutor_email="tutor1@ucb.edu.bo",
                    )
                )

                enrolled = repo.enroll(
                    session.id,
                    student_id="student-1",
                    student_name="Student One",
                    student_email="student1@ucb.edu.bo",
                )

                self.assertEqual(enrolled.enrolled_count, 1)
                self.assertEqual(enrolled.seats_left, 1)
                self.assertEqual(len(repo.list_for_student("student-1")), 1)

                with self.assertRaisesRegex(ValueError, "Ya estas inscrito"):
                    repo.enroll(
                        session.id,
                        student_id="student-1",
                        student_name="Student One",
                        student_email="student1@ucb.edu.bo",
                    )

                cancelled = repo.unenroll(session.id, student_id="student-1")
                self.assertEqual(cancelled.enrolled_count, 0)
                self.assertEqual(cancelled.seats_left, 2)
                self.assertEqual(repo.list_for_student("student-1"), [])

class ReservationReminderSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_scheduler_sends_24h_and_30m_reminders_once_each(self) -> None:
        base_start = datetime(2026, 4, 12, 12, 0, 0)
        reservation = _reservation(status="approved", reservation_id="res-rem-1").model_copy(
            update={
                "start_at": base_start.isoformat(),
                "end_at": (base_start + timedelta(hours=1)).isoformat(),
                "is_active": True,
                "requested_by": "student-1",
            }
        )

        notifications = _FakeNotificationStore()
        realtime = _FakeRealtimeManager()
        source = _FakeReservationSource([reservation])
        scheduler = reminder_scheduler.ReservationReminderScheduler()

        with patch.object(reminder_scheduler, "lab_reservation_repo", source), \
             patch.object(reminder_scheduler, "notification_store", notifications), \
             patch.object(reminder_scheduler, "realtime_manager", realtime):
            await scheduler.run_once(now=base_start - timedelta(hours=23, minutes=59))
            await scheduler.run_once(now=base_start - timedelta(minutes=29))
            await scheduler.run_once(now=base_start - timedelta(minutes=29))

        self.assertEqual(len(notifications.created), 2)
        self.assertEqual(
            [item["payload"]["reminder_kind"] for item in notifications.created],
            ["24h", "30m"],
        )
        self.assertEqual(len(realtime.events), 2)

    async def test_scheduler_skips_non_approved_inactive_or_without_requester(self) -> None:
        base_start = datetime(2026, 4, 12, 12, 0, 0)
        pending = _reservation(status="pending", reservation_id="res-rem-2").model_copy(
            update={
                "start_at": base_start.isoformat(),
                "end_at": (base_start + timedelta(hours=1)).isoformat(),
                "is_active": True,
            }
        )
        inactive = _reservation(status="approved", reservation_id="res-rem-3").model_copy(
            update={
                "start_at": base_start.isoformat(),
                "end_at": (base_start + timedelta(hours=1)).isoformat(),
                "is_active": False,
            }
        )
        no_requester = _reservation(status="approved", reservation_id="res-rem-4").model_copy(
            update={
                "start_at": base_start.isoformat(),
                "end_at": (base_start + timedelta(hours=1)).isoformat(),
                "requested_by": "",
            }
        )

        notifications = _FakeNotificationStore()
        realtime = _FakeRealtimeManager()
        source = _FakeReservationSource([pending, inactive, no_requester])
        scheduler = reminder_scheduler.ReservationReminderScheduler()

        with patch.object(reminder_scheduler, "lab_reservation_repo", source), \
             patch.object(reminder_scheduler, "notification_store", notifications), \
             patch.object(reminder_scheduler, "realtime_manager", realtime):
            await scheduler.run_once(now=base_start - timedelta(minutes=29))

        self.assertEqual(notifications.created, [])
        self.assertEqual(realtime.events, [])

    def test_tutor_cannot_publish_tutorial_that_overlaps_own_lab_reservation(self) -> None:
        start_at, end_at, day = _future_range(days=5, start_hour=14)
        reservation = _reservation(status="approved", requested_by="tutor-1").model_copy(
            update={"start_at": start_at, "end_at": end_at},
        )

        with TemporaryDirectory() as temp_dir:
            storage_path = Path(temp_dir) / "tutorial_sessions.json"
            with patch.object(settings, "tutorial_sessions_storage_path", str(storage_path)):
                repo = TutorialSessionRepository(_StubReservationRepo([reservation]))

                with self.assertRaisesRegex(ValueError, "cruza con una reserva de laboratorio propia"):
                    repo.create(
                        TutorialSessionCreate(
                            topic="Tutoria de Fisica",
                            description="Ondas y movimiento",
                            laboratory_id="lab-1",
                            location="Laboratorio 101",
                            session_date=day,
                            start_time="14:00",
                            end_time="15:00",
                            max_students=3,
                            tutor_id="tutor-1",
                            tutor_name="Tutor Uno",
                            tutor_email="tutor1@ucb.edu.bo",
                        )
                    )


class NotificationAcceptanceTests(unittest.TestCase):
    def test_schedule_change_notification_includes_readable_laboratory_names(self) -> None:
        previous = _reservation(status="approved", reservation_id="res-4").model_copy(update={"laboratory_id": "lab-old"})
        updated = previous.model_copy(update={"laboratory_id": "lab-new"})

        with patch.object(
            reservation_endpoints,
            "laboratory_access_repo",
            _FakeLaboratoryAccessRepo(
                {
                    "lab-old": {"id": "lab-old", "name": "Lab Redes"},
                    "lab-new": {"id": "lab-new", "name": "Lab IoT"},
                }
            ),
        ):
            title, message, payload = reservation_endpoints._build_schedule_change_payload(
                previous,
                updated,
                {"user_id": "admin-1", "name": "Administrador"},
            )

        self.assertEqual(title, "Cambio de Laboratorio")
        self.assertEqual(message, "Tu reserva cambio de espacio fisico. Revisa el laboratorio actualizado.")
        self.assertEqual(payload["old_laboratory_name"], "Lab Redes")
        self.assertEqual(payload["new_laboratory_name"], "Lab IoT")

    def test_schedule_change_does_not_notify_when_actor_is_same_user(self) -> None:
        import asyncio

        previous = _reservation(status="approved", reservation_id="res-5", requested_by="student-1")
        updated = previous.model_copy(update={"laboratory_id": "lab-2"})
        notifications = _FakeNotificationStore()
        realtime = _FakeRealtimeManager()

        async def _run() -> None:
            with patch.object(reservation_endpoints, "notification_store", notifications), \
                 patch.object(reservation_endpoints, "realtime_manager", realtime):
                await reservation_endpoints._notify_schedule_change(
                    previous,
                    updated,
                    {"user_id": "student-1", "name": "Student One"},
                )

        asyncio.run(_run())

        self.assertEqual(notifications.created, [])
        self.assertEqual(realtime.events, [])

    def test_invalid_early_reminders_are_hidden_from_user_list(self) -> None:
        bucket_user = "student-1"
        invalid_24h = UserNotificationResponse(
            id="notif-24h",
            recipient_user_id=bucket_user,
            notification_type="reservation_reminder",
            title="Recordatorio de Reserva",
            message="Tu reserva aprobada comienza en 24 horas.",
            payload={
                "reservation_id": "res-1",
                "reminder_kind": "24h",
                "starts_at": "2026-04-09 18:00:00.000Z",
            },
            is_read=False,
            created_at="2026-04-09T17:53:00Z",
        )
        invalid_30m = UserNotificationResponse(
            id="notif-30m",
            recipient_user_id=bucket_user,
            notification_type="reservation_reminder",
            title="Recordatorio Cercano",
            message="Tu reserva aprobada comienza en 30 minutos.",
            payload={
                "reservation_id": "res-1",
                "reminder_kind": "30m",
                "starts_at": "2026-04-09 18:00:00.000Z",
            },
            is_read=False,
            created_at="2026-04-09T17:53:00Z",
        )
        valid_status = UserNotificationResponse(
            id="notif-status",
            recipient_user_id=bucket_user,
            notification_type="reservation_status_update",
            title="Reserva Confirmada",
            message="Tu solicitud fue aceptada.",
            payload={"reservation_id": "res-1", "status": "approved"},
            is_read=False,
            created_at="2026-04-09T17:53:00Z",
        )

        class _FakeNotificationStore:
            def list_for_user(self, recipient_user_id: str):
                if recipient_user_id != bucket_user:
                    return []
                return [invalid_24h, invalid_30m, valid_status]

        current_user = {"user_id": bucket_user, "permissions": [], "role": "student"}

        with patch.object(notification_endpoints, "notification_store", _FakeNotificationStore()):
            notifications = notification_endpoints.list_my_notifications(current_user=current_user)

        self.assertEqual([item.id for item in notifications], ["notif-status"])


if __name__ == "__main__":
    unittest.main()