from datetime import datetime
from unittest.mock import patch
from app.api.v1.endpoints import analytics as analytics_endpoints
from app.schemas.lab_block import LabBlockResponse
from app.schemas.lab_schedule import LabScheduleResponse
from app.schemas.lab_reservation import LabReservationResponse


def _reservation(*, reservation_id, laboratory_id, status, start_at, end_at):
    created = datetime(2026, 4, 20, 8, 0, 0).isoformat()
    return LabReservationResponse(
        id=reservation_id,
        laboratory_id=laboratory_id,
        area_id='area-1',
        requested_by='user-1',
        purpose='Practica',
        start_at=start_at,
        end_at=end_at,
        status=status,
        attendees_count=1,
        notes='',
        approved_by='admin-1',
        approved_at=created,
        cancel_reason='',
        is_active=status not in {'cancelled', 'rejected', 'absent'},
        created=created,
        updated=created,
        requested_by_name='User One',
        requested_by_email='user1@ucb.edu.bo',
        station_label='',
        check_in_at='',
        check_out_at='',
        is_walk_in=False,
        user_modification_count=0,
    )

class _FakeListRepository:
    def __init__(self, items):
        self._items = items
    def list_all(self):
        return list(self._items)
    def list_active_in_window(self, *, start_from, end_to, per_page=200):
        return list(self._items)
    def list_in_window_by_statuses(self, *, statuses, start_from, end_to, per_page=200):
        filtered = []
        for item in self._items:
            if getattr(item, 'status', None) in statuses:
                filtered.append(item)
        return filtered
    def list_all_active(self):
        filtered = []
        for item in self._items:
            if getattr(item, 'is_active', True):
                filtered.append(item)
        return filtered

laboratories = [
    {'id': 'lab-1', 'name': 'Lab Redes', 'location': 'Bloque A', 'area_id': 'area-a', 'is_active': True, 'expand': {'area_id': {'name': 'Ingenieria'}}},
    {'id': 'lab-2', 'name': 'Lab Robotica', 'location': 'Bloque B', 'area_id': 'area-b', 'is_active': True, 'expand': {'area_id': {'name': 'Mecatronica'}}}
]
schedules = [
    LabScheduleResponse(id='sch-1', laboratory_id='lab-1', weekday=0, open_time='08:00', close_time='12:00', slot_minutes=60, is_active=True, created='', updated=''),
    LabScheduleResponse(id='sch-2', laboratory_id='lab-2', weekday=0, open_time='08:00', close_time='12:00', slot_minutes=60, is_active=True, created='', updated='')
]
blocks = [
    LabBlockResponse(id='blk-1', laboratory_id='lab-2', start_at='2026-04-20T09:00:00', end_at='2026-04-20T10:00:00', reason='Mantenimiento', block_type='maintenance', created_by='admin-1', is_active=True, created='', updated='')
]
reservations = [
    _reservation(reservation_id='res-1', laboratory_id='lab-1', status='approved', start_at='2026-04-20T08:00:00', end_at='2026-04-20T09:00:00'),
    _reservation(reservation_id='res-2', laboratory_id='lab-1', status='completed', start_at='2026-04-20T09:00:00', end_at='2026-04-20T10:00:00'),
    _reservation(reservation_id='res-3', laboratory_id='lab-1', status='pending', start_at='2026-04-20T10:00:00', end_at='2026-04-20T11:00:00'),
    _reservation(reservation_id='res-4', laboratory_id='lab-2', status='completed', start_at='2026-04-20T08:00:00', end_at='2026-04-20T09:00:00')
]
current_user = {'user_id': 'admin-1', 'permissions': ['gestionar_reservas'], 'role': 'admin'}
with patch.object(analytics_endpoints, 'laboratory_access_repo', _FakeListRepository(laboratories)), \
     patch.object(analytics_endpoints, 'lab_schedule_repo', _FakeListRepository(schedules)), \
     patch.object(analytics_endpoints, 'lab_block_repo', _FakeListRepository(blocks)), \
     patch.object(analytics_endpoints, 'lab_reservation_repo', _FakeListRepository(reservations)), \
     patch.object(analytics_endpoints, 'now_local_naive', lambda: datetime(2026, 4, 20, 10, 0, 0)):
    response = analytics_endpoints.get_laboratory_usage_analytics(period='daily', current_user=current_user)
    print('totals', response.totals.available_blocks, response.totals.used_blocks, response.totals.blocked_blocks, response.totals.completed_blocks, response.totals.reserved_blocks)
    print([(item.laboratory_id, item.available_blocks, item.used_blocks, item.blocked_blocks, item.completed_blocks, item.reserved_blocks, item.occupancy_percentage) for item in response.labs])
