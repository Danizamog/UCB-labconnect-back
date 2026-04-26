from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch

from app.api.v1.endpoints import analytics as analytics_endpoints
from app.schemas.lab_block import LabBlockResponse
from app.schemas.lab_reservation import LabReservationResponse
from app.schemas.lab_schedule import LabScheduleResponse


def _reservation(
    *,
    reservation_id: str,
    laboratory_id: str,
    status: str,
    start_at: str,
    end_at: str,
) -> LabReservationResponse:
    created = datetime(2026, 4, 20, 8, 0, 0).isoformat()
    return LabReservationResponse(
        id=reservation_id,
        laboratory_id=laboratory_id,
        area_id="area-1",
        requested_by="user-1",
        purpose="Practica",
        start_at=start_at,
        end_at=end_at,
        status=status,
        attendees_count=1,
        notes="",
        approved_by="admin-1",
        approved_at=created,
        cancel_reason="",
        is_active=status not in {"cancelled", "rejected", "absent"},
        created=created,
        updated=created,
        requested_by_name="User One",
        requested_by_email="user1@ucb.edu.bo",
        station_label="",
        check_in_at="",
        check_out_at="",
        is_walk_in=False,
        user_modification_count=0,
    )


class _FakeListRepository:
    def __init__(self, items):
        self._items = items

    def list_all(self):
        return list(self._items)


class LaboratoryUsageAnalyticsTests(unittest.TestCase):
    def test_daily_usage_analytics_counts_available_used_and_ranking(self) -> None:
        laboratories = [
            {
                "id": "lab-1",
                "name": "Lab Redes",
                "location": "Bloque A",
                "area_id": "area-a",
                "is_active": True,
                "expand": {"area_id": {"name": "Ingenieria"}},
            },
            {
                "id": "lab-2",
                "name": "Lab Robotica",
                "location": "Bloque B",
                "area_id": "area-b",
                "is_active": True,
                "expand": {"area_id": {"name": "Mecatronica"}},
            },
        ]
        schedules = [
            LabScheduleResponse(
                id="sch-1",
                laboratory_id="lab-1",
                weekday=0,
                open_time="08:00",
                close_time="12:00",
                slot_minutes=60,
                is_active=True,
                created="",
                updated="",
            ),
            LabScheduleResponse(
                id="sch-2",
                laboratory_id="lab-2",
                weekday=0,
                open_time="08:00",
                close_time="12:00",
                slot_minutes=60,
                is_active=True,
                created="",
                updated="",
            ),
        ]
        blocks = [
            LabBlockResponse(
                id="blk-1",
                laboratory_id="lab-2",
                start_at="2026-04-20T09:00:00",
                end_at="2026-04-20T10:00:00",
                reason="Mantenimiento",
                block_type="maintenance",
                created_by="admin-1",
                is_active=True,
                created="",
                updated="",
            )
        ]
        reservations = [
            _reservation(
                reservation_id="res-1",
                laboratory_id="lab-1",
                status="approved",
                start_at="2026-04-20T08:00:00",
                end_at="2026-04-20T09:00:00",
            ),
            _reservation(
                reservation_id="res-2",
                laboratory_id="lab-1",
                status="completed",
                start_at="2026-04-20T09:00:00",
                end_at="2026-04-20T10:00:00",
            ),
            _reservation(
                reservation_id="res-3",
                laboratory_id="lab-1",
                status="pending",
                start_at="2026-04-20T10:00:00",
                end_at="2026-04-20T11:00:00",
            ),
            _reservation(
                reservation_id="res-4",
                laboratory_id="lab-2",
                status="completed",
                start_at="2026-04-20T08:00:00",
                end_at="2026-04-20T09:00:00",
            ),
        ]

        current_user = {"user_id": "admin-1", "permissions": ["gestionar_reservas"], "role": "admin"}

        with patch.object(analytics_endpoints, "laboratory_access_repo", _FakeListRepository(laboratories)), \
             patch.object(analytics_endpoints, "lab_schedule_repo", _FakeListRepository(schedules)), \
             patch.object(analytics_endpoints, "lab_block_repo", _FakeListRepository(blocks)), \
             patch.object(analytics_endpoints, "lab_reservation_repo", _FakeListRepository(reservations)), \
             patch.object(analytics_endpoints, "now_local_naive", lambda: datetime(2026, 4, 20, 10, 0, 0)):
            response = analytics_endpoints.get_laboratory_usage_analytics(period="daily", current_user=current_user)

        self.assertEqual(response.period, "daily")
        self.assertEqual(response.start_date, "2026-04-20")
        self.assertEqual(response.end_date, "2026-04-20")
        self.assertEqual(response.totals.available_blocks, 7)
        self.assertEqual(response.totals.blocked_blocks, 1)
        self.assertEqual(response.totals.used_blocks, 3)
        self.assertEqual(response.totals.reserved_blocks, 1)
        self.assertEqual(response.totals.completed_blocks, 2)
        self.assertEqual(response.totals.occupancy_percentage, 42.86)
        self.assertEqual([item.laboratory_id for item in response.labs], ["lab-1", "lab-2"])
        self.assertEqual(response.highest_usage_laboratory.laboratory_id, "lab-1")
        self.assertEqual(response.lowest_usage_laboratory.laboratory_id, "lab-2")
        self.assertEqual(response.labs[0].available_blocks, 4)
        self.assertEqual(response.labs[0].used_blocks, 2)
        self.assertEqual(response.labs[0].occupancy_percentage, 50.0)
        self.assertEqual(response.labs[1].available_blocks, 3)
        self.assertEqual(response.labs[1].blocked_blocks, 1)
        self.assertEqual(response.labs[1].used_blocks, 1)
        self.assertEqual(response.labs[1].occupancy_percentage, 33.33)

    def test_weekly_and_monthly_periods_are_accumulative_to_today(self) -> None:
        laboratories = [
            {
                "id": "lab-1",
                "name": "Lab Datos",
                "location": "Bloque C",
                "area_id": "area-c",
                "is_active": True,
                "expand": {"area_id": {"name": "Tecnologia"}},
            }
        ]
        schedules = [
            LabScheduleResponse(
                id="sch-1",
                laboratory_id="lab-1",
                weekday=0,
                open_time="08:00",
                close_time="10:00",
                slot_minutes=60,
                is_active=True,
                created="",
                updated="",
            ),
            LabScheduleResponse(
                id="sch-2",
                laboratory_id="lab-1",
                weekday=3,
                open_time="08:00",
                close_time="10:00",
                slot_minutes=60,
                is_active=True,
                created="",
                updated="",
            ),
        ]
        reservations = [
            _reservation(
                reservation_id="res-week",
                laboratory_id="lab-1",
                status="completed",
                start_at="2026-04-20T08:00:00",
                end_at="2026-04-20T09:00:00",
            ),
            _reservation(
                reservation_id="res-month",
                laboratory_id="lab-1",
                status="approved",
                start_at="2026-04-02T08:00:00",
                end_at="2026-04-02T09:00:00",
            ),
        ]

        current_user = {"user_id": "admin-1", "permissions": ["gestionar_reservas"], "role": "admin"}

        with patch.object(analytics_endpoints, "laboratory_access_repo", _FakeListRepository(laboratories)), \
             patch.object(analytics_endpoints, "lab_schedule_repo", _FakeListRepository(schedules)), \
             patch.object(analytics_endpoints, "lab_block_repo", _FakeListRepository([])), \
             patch.object(analytics_endpoints, "lab_reservation_repo", _FakeListRepository(reservations)), \
             patch.object(analytics_endpoints, "now_local_naive", lambda: datetime(2026, 4, 23, 9, 0, 0)):
            weekly = analytics_endpoints.get_laboratory_usage_analytics(period="weekly", current_user=current_user)
            monthly = analytics_endpoints.get_laboratory_usage_analytics(period="monthly", current_user=current_user)

        self.assertEqual(weekly.start_date, "2026-04-20")
        self.assertEqual(weekly.end_date, "2026-04-23")
        self.assertEqual(weekly.totals.used_blocks, 1)
        self.assertEqual(monthly.start_date, "2026-04-01")
        self.assertEqual(monthly.end_date, "2026-04-23")
        self.assertEqual(monthly.totals.used_blocks, 2)


if __name__ == "__main__":
    unittest.main()
