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

    def update(self, reservation_id: str, body):
        if self.current.id != reservation_id:
            return None
        payload = {key: value for key, value in body.model_dump().items() if value is not None}
        if payload.get("status") == "cancelled":
            self.cancel_calls.append(reservation_id)
        self.current = self.current.model_copy(update=payload)
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
        self.calls: list[tuple] = []

    def list_all(self):
        self.calls.append(("list_all",))
        return list(self._items)

    def get_active_for_laboratory_weekday(self, laboratory_id: str, weekday: int):
        self.calls.append(("get_active_for_laboratory_weekday", laboratory_id, weekday))
        return self._items[0] if self._items else None

    def list_for_laboratory_day(self, laboratory_id: str, day: str):
        self.calls.append(("list_for_laboratory_day", laboratory_id, day))
        return list(self._items)

    def list_public_for_laboratory_day(self, laboratory_id: str, day: str):
        self.calls.append(("list_public_for_laboratory_day", laboratory_id, day))
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

    def list_public_for_laboratory_day(self, laboratory_id: str, day: str):
        return []


class _FakeReservationSource:
    def __init__(self, reservations: list[LabReservationResponse]) -> None:
        self._reservations = reservations

    def list_all(self):
        return list(self._reservations)

    def list_for_laboratory_day(self, laboratory_id: str, day: str):
        return list(self._reservations)


class _FakeReservationByIdRepo:
    def __init__(self, reservations: dict[str, LabReservationResponse] | None = None) -> None:
        self._reservations = reservations or {}

    def get_by_id(self, reservation_id: str) -> LabReservationResponse | None:
        return self._reservations.get(reservation_id)


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

        self.assertEqual(response.status, "cancelled")
        self.assertFalse(response.is_active)
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


class ReservationHistoryTests(unittest.TestCase):
    def test_history_returns_only_past_or_closed_reservations_for_current_user(self) -> None:
        now = datetime(2026, 4, 18, 12, 0, 0)
        past_completed = _reservation(status="completed", reservation_id="res-history-1").model_copy(
            update={
                "start_at": datetime(2026, 4, 15, 9, 0, 0).isoformat(),
                "end_at": datetime(2026, 4, 15, 10, 0, 0).isoformat(),
            }
        )
        past_approved = _reservation(status="approved", reservation_id="res-history-2").model_copy(
            update={
                "start_at": datetime(2026, 4, 17, 14, 0, 0).isoformat(),
                "end_at": datetime(2026, 4, 17, 15, 0, 0).isoformat(),
            }
        )
        future_cancelled = _reservation(status="cancelled", reservation_id="res-history-3").model_copy(
            update={
                "start_at": datetime(2026, 4, 21, 11, 0, 0).isoformat(),
                "end_at": datetime(2026, 4, 21, 12, 0, 0).isoformat(),
            }
        )
        other_user_past = _reservation(status="completed", reservation_id="res-history-4", requested_by="student-2").model_copy(
            update={
                "start_at": datetime(2026, 4, 14, 11, 0, 0).isoformat(),
                "end_at": datetime(2026, 4, 14, 12, 0, 0).isoformat(),
            }
        )

        current_user = {"user_id": "student-1", "permissions": [], "role": "student"}
        enrich_repo = type("_AccessRepo", (), {"enrich_reservations": lambda self, items: items})()

        with patch.object(reservation_endpoints, "lab_reservation_repo", _StubReservationRepo([
            past_completed,
            past_approved,
            future_cancelled,
            other_user_past,
        ])), \
             patch.object(reservation_endpoints, "lab_access_session_repo", enrich_repo), \
             patch.object(reservation_endpoints, "now_local_naive", lambda: now):
            page = reservation_endpoints.search_my_reservation_history(
                page_number=0,
                page_size=10,
                sort_by="start_at",
                sort_type="DESC",
                current_user=current_user,
            )

        self.assertEqual(page.totalElements, 2)
        self.assertEqual([item.id for item in page.items], ["res-history-2", "res-history-1"])

    def test_history_supports_pagination(self) -> None:
        now = datetime(2026, 4, 18, 12, 0, 0)
        reservations = []
        for index in range(4):
            day = 17 - index
            reservations.append(
                _reservation(status="completed", reservation_id=f"res-page-{index + 1}").model_copy(
                    update={
                        "start_at": datetime(2026, 4, day, 9, 0, 0).isoformat(),
                        "end_at": datetime(2026, 4, day, 10, 0, 0).isoformat(),
                    }
                )
            )

        current_user = {"user_id": "student-1", "permissions": [], "role": "student"}
        enrich_repo = type("_AccessRepo", (), {"enrich_reservations": lambda self, items: items})()

        with patch.object(reservation_endpoints, "lab_reservation_repo", _StubReservationRepo(reservations)), \
             patch.object(reservation_endpoints, "lab_access_session_repo", enrich_repo), \
             patch.object(reservation_endpoints, "now_local_naive", lambda: now):
            page = reservation_endpoints.search_my_reservation_history(
                page_number=1,
                page_size=2,
                sort_by="start_at",
                sort_type="DESC",
                current_user=current_user,
            )

        self.assertEqual(page.totalElements, 4)
        self.assertEqual(page.totalPages, 2)
        self.assertEqual([item.id for item in page.items], ["res-page-3", "res-page-4"])


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


class AvailabilityFilterUsageTests(unittest.TestCase):
    def test_availability_uses_day_specific_repository_queries(self) -> None:
        start_at, _, day = _future_range(days=4, start_hour=11)
        fake_now = datetime.fromisoformat(start_at) - timedelta(days=1)
        schedule = type(
            "_Schedule",
            (),
            {"open_time": "08:00", "close_time": "20:00", "slot_minutes": 60, "laboratory_id": "lab-1", "weekday": fake_now.weekday(), "is_active": True},
        )()

        schedule_repo = _FakeListRepo([schedule])
        block_repo = _FakeListRepo([])
        reservation_repo = _FakeListRepo([])
        tutorial_repo = _FakeListRepo([])

        with patch.object(availability_endpoints, "ensure_user_can_reserve_laboratory", lambda *args, **kwargs: None), \
             patch.object(availability_endpoints, "lab_schedule_repo", schedule_repo), \
             patch.object(availability_endpoints, "lab_block_repo", block_repo), \
             patch.object(availability_endpoints, "lab_reservation_repo", reservation_repo), \
             patch.object(availability_endpoints, "tutorial_session_repo", tutorial_repo), \
             patch.object(availability_endpoints, "now_local_naive", lambda: fake_now):
            availability_endpoints.get_lab_availability("lab-1", day=day, current_user={"user_id": "student-1", "permissions": [], "role": "student"})

        self.assertEqual(schedule_repo.calls[0], ("get_active_for_laboratory_weekday", "lab-1", datetime.fromisoformat(day).weekday()))
        self.assertEqual(block_repo.calls[0], ("list_for_laboratory_day", "lab-1", day))
        self.assertEqual(reservation_repo.calls[0], ("list_for_laboratory_day", "lab-1", day))
        self.assertEqual(tutorial_repo.calls[0], ("list_public_for_laboratory_day", "lab-1", day))


class ReservationValidationFilterUsageTests(unittest.TestCase):
    def test_reservation_validation_uses_day_specific_repository_queries(self) -> None:
        start_at, end_at, _ = _future_range(days=5, start_hour=13)
        day = datetime.fromisoformat(start_at).date().isoformat()
        schedule = type(
            "_Schedule",
            (),
            {"open_time": "08:00", "close_time": "20:00", "slot_minutes": 60, "laboratory_id": "lab-1", "weekday": datetime.fromisoformat(start_at).weekday(), "is_active": True},
        )()

        schedule_repo = _FakeListRepo([schedule])
        block_repo = _FakeListRepo([])
        reservation_repo = _FakeListRepo([])
        tutorial_repo = _FakeListRepo([])

        with patch.object(reservation_endpoints, "lab_schedule_repo", schedule_repo), \
             patch.object(reservation_endpoints, "lab_block_repo", block_repo), \
             patch.object(reservation_endpoints, "lab_reservation_repo", reservation_repo), \
             patch.object(reservation_endpoints, "tutorial_session_repo", tutorial_repo), \
             patch.object(reservation_endpoints, "now_local_naive", lambda: datetime.fromisoformat(start_at) - timedelta(days=1)):
            reservation_endpoints._validate_reservation_time_rules(
                laboratory_id="lab-1",
                start_at_raw=start_at,
                end_at_raw=end_at,
            )

        self.assertEqual(schedule_repo.calls[0], ("get_active_for_laboratory_weekday", "lab-1", datetime.fromisoformat(start_at).weekday()))
        self.assertEqual(block_repo.calls[0], ("list_for_laboratory_day", "lab-1", day))
        self.assertEqual(reservation_repo.calls[0], ("list_for_laboratory_day", "lab-1", day))
        self.assertEqual(tutorial_repo.calls[0], ("list_public_for_laboratory_day", "lab-1", day))


class _StubReservationRepo:
    def __init__(self, reservations: list[LabReservationResponse] | None = None) -> None:
        self._reservations = reservations or []

    def list_all(self) -> list[LabReservationResponse]:
        return list(self._reservations)

    def list_for_laboratory_day(self, laboratory_id: str, day: str) -> list[LabReservationResponse]:
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

    def test_cancelled_reminder_is_hidden_from_user_list(self) -> None:
        bucket_user = "student-1"
        reminder = UserNotificationResponse(
            id="notif-cancelled-reminder",
            recipient_user_id=bucket_user,
            notification_type="reservation_reminder",
            title="Recordatorio de Reserva",
            message="Tu reserva aprobada comienza en 24 horas.",
            payload={
                "reservation_id": "res-cancelled",
                "reminder_kind": "24h",
                "starts_at": "2026-04-10 18:00:00.000Z",
            },
            is_read=False,
            created_at="2026-04-09T18:00:00Z",
        )

        cancelled_reservation = _reservation(status="cancelled", reservation_id="res-cancelled").model_copy(
            update={
                "start_at": "2026-04-10 18:00:00.000Z",
                "end_at": "2026-04-10 19:00:00.000Z",
                "is_active": False,
            }
        )

        class _FakeNotificationStore:
            def list_for_user(self, recipient_user_id: str):
                if recipient_user_id != bucket_user:
                    return []
                return [reminder]

        current_user = {"user_id": bucket_user, "permissions": [], "role": "student"}

        with patch.object(notification_endpoints, "notification_store", _FakeNotificationStore()), \
             patch.object(notification_endpoints, "lab_reservation_repo", _FakeReservationByIdRepo({"res-cancelled": cancelled_reservation})), \
             patch.object(notification_endpoints, "now_local_naive", lambda: datetime(2026, 4, 9, 17, 0, 0)):
            notifications = notification_endpoints.list_my_notifications(current_user=current_user)

        self.assertEqual(notifications, [])

    def test_modified_reminder_is_hidden_from_user_list(self) -> None:
        bucket_user = "student-1"
        reminder = UserNotificationResponse(
            id="notif-modified-reminder",
            recipient_user_id=bucket_user,
            notification_type="reservation_reminder",
            title="Recordatorio de Reserva",
            message="Tu reserva aprobada comienza en 24 horas.",
            payload={
                "reservation_id": "res-modified",
                "reminder_kind": "24h",
                "starts_at": "2026-04-10 18:00:00.000Z",
            },
            is_read=False,
            created_at="2026-04-09T18:00:00Z",
        )

        modified_reservation = _reservation(status="approved", reservation_id="res-modified").model_copy(
            update={
                "start_at": "2026-04-10 19:00:00.000Z",
                "end_at": "2026-04-10 20:00:00.000Z",
                "is_active": True,
            }
        )

        class _FakeNotificationStore:
            def list_for_user(self, recipient_user_id: str):
                if recipient_user_id != bucket_user:
                    return []
                return [reminder]

        current_user = {"user_id": bucket_user, "permissions": [], "role": "student"}

        with patch.object(notification_endpoints, "notification_store", _FakeNotificationStore()), \
             patch.object(notification_endpoints, "lab_reservation_repo", _FakeReservationByIdRepo({"res-modified": modified_reservation})), \
             patch.object(notification_endpoints, "now_local_naive", lambda: datetime(2026, 4, 9, 17, 0, 0)):
            notifications = notification_endpoints.list_my_notifications(current_user=current_user)

        self.assertEqual(notifications, [])

    def test_expired_reminder_is_hidden_from_user_list(self) -> None:
        bucket_user = "student-1"
        expired = UserNotificationResponse(
            id="notif-expired-reminder",
            recipient_user_id=bucket_user,
            notification_type="reservation_reminder",
            title="Recordatorio de Reserva",
            message="Tu reserva aprobada comienza en 24 horas.",
            payload={
                "reservation_id": "res-expired",
                "reminder_kind": "24h",
                "starts_at": "2026-04-09 18:00:00.000Z",
            },
            is_read=False,
            created_at="2026-04-08T18:00:00Z",
        )

        reservation = _reservation(status="approved", reservation_id="res-expired").model_copy(
            update={
                "start_at": "2026-04-09 18:00:00.000Z",
                "end_at": "2026-04-09 19:00:00.000Z",
                "is_active": True,
            }
        )

        class _FakeNotificationStore:
            def list_for_user(self, recipient_user_id: str):
                if recipient_user_id != bucket_user:
                    return []
                return [expired]

        current_user = {"user_id": bucket_user, "permissions": [], "role": "student"}

        with patch.object(notification_endpoints, "notification_store", _FakeNotificationStore()), \
             patch.object(notification_endpoints, "lab_reservation_repo", _FakeReservationByIdRepo({"res-expired": reservation})), \
             patch.object(notification_endpoints, "now_local_naive", lambda: datetime(2026, 4, 9, 19, 0, 0)):
            notifications = notification_endpoints.list_my_notifications(current_user=current_user)

        self.assertEqual(notifications, [])


if __name__ == "__main__":
    unittest.main()