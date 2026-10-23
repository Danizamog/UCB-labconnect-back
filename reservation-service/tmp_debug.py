from datetime import date, datetime
from app.api.v1.endpoints.analytics import _has_overlap
from app.core.datetime_utils import iter_lab_blocks
from app.schemas.lab_schedule import LabScheduleResponse

current_day = date(2026, 4, 20)
schedules_for_day = [
    LabScheduleResponse(id='sch-1', laboratory_id='lab-1', weekday=0, open_time='08:00', close_time='12:00', slot_minutes=60, is_active=True, created='', updated='')
]
slot_windows = []
for schedule in schedules_for_day:
    schedule_start = getattr(schedule, 'start_time', getattr(schedule, 'open_time', '00:00'))
    schedule_end = getattr(schedule, 'end_time', getattr(schedule, 'close_time', '00:00'))
    schedule_slot_minutes = getattr(schedule, 'slot_minutes', None)
    slot_windows.extend(iter_lab_blocks(current_day, start_time=schedule_start, end_time=schedule_end, slot_minutes=schedule_slot_minutes))
print(slot_windows)
print('len', len(slot_windows))

blocks = []
# simulate reservation
reserva = {'status': 'approved', 'start_at': '2026-04-20T08:00:00', 'end_at': '2026-04-20T09:00:00'}

available = 0
used = 0
for slot_start, slot_end in slot_windows:
    is_blocked = any(_has_overlap(slot_start, slot_end, block['start_at'], block['end_at']) for block in blocks)
    if is_blocked:
        continue
    available += 1
    matching = None
    if reserva['status'] in {'approved','in_progress','completed'} and _has_overlap(slot_start, slot_end, reserva['start_at'], reserva['end_at']):
        matching = reserva
    if matching is not None:
        used += 1
print('available', available)
print('used', used)
