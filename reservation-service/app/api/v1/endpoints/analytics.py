from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status

logger = logging.getLogger(__name__)

from app.application.container import lab_block_repo, lab_reservation_repo, lab_schedule_repo, laboratory_access_repo
from app.core.datetime_utils import combine_date_time, iter_lab_blocks, now_local_naive, parse_datetime
from app.core.dependencies import ensure_any_permission, get_current_user
from app.schemas.lab_analytics import (
    ANALYTICS_PERIODS,
    HourlyUsage,
    WeekdayUsage,
    LaboratoryUsageAnalyticsResponse,
    LaboratoryUsageStats,
    LaboratoryUsageTotals,
)

router = APIRouter(prefix="/reservations/analytics", tags=["reservation-analytics"])

_MANAGEMENT_PERMISSIONS = {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"}
# La vista de Analisis del frontend se muestra con consultar_estadisticas; el backend
# debe aceptar ese mismo permiso ademas de los de gestion para no devolver 403 a quien
# ve el menu (alineacion frontend/backend del RBAC).
_VIEW_ANALYTICS_PERMISSIONS = _MANAGEMENT_PERMISSIONS | {"consultar_estadisticas"}
_COUNTED_RESERVATION_STATUSES = {"approved", "in_progress", "completed"}


def _round_percentage(used_blocks: int, available_blocks: int) -> float:
    if available_blocks <= 0:
        return 0.0
    return round((used_blocks / available_blocks) * 100, 2)


def _has_overlap(slot_start, slot_end, event_start_raw: str, event_end_raw: str) -> bool:
    event_start = parse_datetime(event_start_raw)
    event_end = parse_datetime(event_end_raw)
    return slot_start < event_end and event_start < slot_end


def _resolve_period_window(period: str, today: date) -> tuple[date, date, str]:
    normalized = str(period or "").strip().lower()
    if normalized not in ANALYTICS_PERIODS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="period debe ser daily, weekly o monthly",
        )

    if normalized == "daily":
        return today, today, "Hoy"

    if normalized == "weekly":
        start_date = today - timedelta(days=today.weekday())
        return start_date, today, "Esta semana"

    start_date = today.replace(day=1)
    return start_date, today, "Este mes"


def _iter_days(start_date: date, end_date: date) -> list[date]:
    days: list[date] = []
    cursor = start_date
    while cursor <= end_date:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _lab_sort_key(item: LaboratoryUsageStats) -> tuple[float, int, int, str]:
    return (-item.occupancy_percentage, -item.used_blocks, -item.completed_blocks, item.laboratory_name.lower())


@router.get("/laboratory-usage", response_model=LaboratoryUsageAnalyticsResponse)
async def get_laboratory_usage_analytics(
    period: str = Query(default="daily"),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
) -> LaboratoryUsageAnalyticsResponse:
    ensure_any_permission(
        current_user,
        _VIEW_ANALYTICS_PERMISSIONS,
        "No tienes permisos para consultar estadisticas de uso por laboratorio",
    )

    today = now_local_naive().date()
    if start_date and end_date:
        s_date, e_date, p_label = start_date, end_date, f"{start_date} al {end_date}"
    else:
        s_date, e_date, p_label = _resolve_period_window(period, today)

    window_start_iso = combine_date_time(s_date, "00:00").isoformat()
    window_end_iso = combine_date_time(e_date + timedelta(days=1), "00:00").isoformat()

    # Las cinco consultas pegan a colecciones distintas en PocketBase; paralelizar
    # reduce la latencia total al maximo round-trip individual. Y pre-cargar todos
    # los lab_schedule activos elimina el patron N x M dentro del bucle de labs/dias.
    laboratories_raw, active_blocks, reservations, all_schedules, all_demand_reservations = await asyncio.gather(
        asyncio.to_thread(laboratory_access_repo.list_all),
        asyncio.to_thread(
            lab_block_repo.list_active_in_window,
            start_from=window_start_iso,
            end_to=window_end_iso,
        ),
        asyncio.to_thread(
            lab_reservation_repo.list_in_window_by_statuses,
            statuses=list(_COUNTED_RESERVATION_STATUSES),
            start_from=window_start_iso,
            end_to=window_end_iso,
        ),
        asyncio.to_thread(lab_schedule_repo.list_all_active),
        asyncio.to_thread(
            lab_reservation_repo.list_in_window_by_statuses,
            statuses=["pending", "approved", "in_progress", "completed", "absent"],
            start_from=window_start_iso,
            end_to=window_end_iso,
        ),
    )
    laboratories = [lab for lab in laboratories_raw if bool(lab.get("is_active", True))]

    schedules_by_lab_weekday: dict[tuple[str, int], list] = defaultdict(list)
    for schedule in all_schedules:
        schedules_by_lab_weekday[(str(schedule.laboratory_id), int(schedule.weekday))].append(schedule)

    blocks_by_lab_day: dict[tuple[str, str], list] = defaultdict(list)
    for block in active_blocks:
        try:
            block_start = parse_datetime(block.start_at)
            block_end = parse_datetime(block.end_at)
        except ValueError:
            continue
        if block_end.date() < s_date or block_start.date() > e_date:
            continue
        blocks_by_lab_day[(str(block.laboratory_id), block_start.date().isoformat())].append(block)

    reservations_by_lab_day: dict[tuple[str, str], list] = defaultdict(list)
    for reservation in reservations:
        try:
            reservation_start = parse_datetime(reservation.start_at)
            reservation_end = parse_datetime(reservation.end_at)
        except ValueError:
            continue
        if reservation_end.date() < s_date or reservation_start.date() > e_date:
            continue
        reservations_by_lab_day[(str(reservation.laboratory_id), reservation_start.date().isoformat())].append(reservation)

    usage_rows: list[LaboratoryUsageStats] = []
    days_in_range = _iter_days(s_date, e_date)

    for laboratory in laboratories:
        laboratory_id = str(laboratory.get("id") or "").strip()
        if not laboratory_id:
            continue

        available_blocks = 0
        blocked_blocks = 0
        used_blocks = 0
        reserved_blocks = 0
        in_progress_blocks = 0
        completed_blocks = 0

        for current_day in days_in_range:
            blocks = blocks_by_lab_day.get((laboratory_id, current_day.isoformat()), [])
            day_reservations = reservations_by_lab_day.get((laboratory_id, current_day.isoformat()), [])
            day_classes = schedules_by_lab_weekday.get((laboratory_id, current_day.weekday()), [])
            class_windows = [
                (combine_date_time(current_day, klass.start_time), combine_date_time(current_day, klass.end_time))
                for klass in day_classes
            ]

            for slot_start, slot_end in iter_lab_blocks(current_day):
                is_blocked_by_class = any(
                    slot_start < class_end and class_start < slot_end
                    for class_start, class_end in class_windows
                )
                if is_blocked_by_class:
                    blocked_blocks += 1
                    continue

                is_blocked = any(_has_overlap(slot_start, slot_end, block.start_at, block.end_at) for block in blocks)
                if is_blocked:
                    blocked_blocks += 1
                    continue

                available_blocks += 1
                matching_reservation = next(
                    (
                        reservation
                        for reservation in day_reservations
                        if _has_overlap(slot_start, slot_end, reservation.start_at, reservation.end_at)
                    ),
                    None,
                )
                if matching_reservation is None:
                    continue

                used_blocks += 1
                if matching_reservation.status == "approved":
                    reserved_blocks += 1
                elif matching_reservation.status == "in_progress":
                    in_progress_blocks += 1
                elif matching_reservation.status == "completed":
                    completed_blocks += 1

        if available_blocks <= 0:
            continue

        area_expand = laboratory.get("expand") or {}
        area_record = area_expand.get("area_id") if isinstance(area_expand, dict) else {}
        area_name = area_record.get("name") if isinstance(area_record, dict) else ""

        usage_rows.append(
            LaboratoryUsageStats(
                laboratory_id=laboratory_id,
                laboratory_name=str(laboratory.get("name") or laboratory_id),
                laboratory_location=str(laboratory.get("location") or ""),
                area_id=str(laboratory.get("area_id") or ""),
                area_name=str(area_name or ""),
                available_blocks=available_blocks,
                blocked_blocks=blocked_blocks,
                used_blocks=used_blocks,
                reserved_blocks=reserved_blocks,
                in_progress_blocks=in_progress_blocks,
                completed_blocks=completed_blocks,
                occupancy_percentage=_round_percentage(used_blocks, available_blocks),
            )
        )

    usage_rows.sort(key=_lab_sort_key)

    total_available_blocks = sum(item.available_blocks for item in usage_rows)
    total_blocked_blocks = sum(item.blocked_blocks for item in usage_rows)
    total_used_blocks = sum(item.used_blocks for item in usage_rows)
    total_reserved_blocks = sum(item.reserved_blocks for item in usage_rows)
    total_in_progress_blocks = sum(item.in_progress_blocks for item in usage_rows)
    total_completed_blocks = sum(item.completed_blocks for item in usage_rows)

    # all_demand_reservations ya se cargo arriba en el gather (cubre todos los estados
    # para la distribucion de demanda horaria/semanal).
    logger.debug("Processing %s reservations for demand distribution", len(all_demand_reservations))

    WEEKDAY_LABELS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    hourly_counts: dict[int, int] = defaultdict(int)
    weekday_counts: dict[int, int] = defaultdict(int)

    for reservation in all_demand_reservations:
        try:
            res_start = parse_datetime(reservation.start_at)
            # Only count hourly if within the reasonable day range (7 AM to 10 PM)
            if 7 <= res_start.hour <= 22:
                hourly_counts[res_start.hour] += 1
            
            # Count weekday
            weekday_counts[res_start.weekday()] += 1
        except (ValueError, AttributeError):
            continue

    logger.debug("Hourly counts: %s", dict(hourly_counts))
    logger.debug("Weekday counts: %s", dict(weekday_counts))

    hourly_usage = [
        HourlyUsage(hour=h, count=hourly_counts[h])
        for h in range(7, 23)
    ]

    weekday_usage = [
        WeekdayUsage(weekday=i, label=WEEKDAY_LABELS[i], count=weekday_counts[i])
        for i in range(7)
    ]

    return LaboratoryUsageAnalyticsResponse(
        period=str(period).strip().lower() if str(period).strip().lower() in ANALYTICS_PERIODS else "daily",
        period_label=p_label,
        start_date=s_date.isoformat(),
        end_date=e_date.isoformat(),
        generated_at=now_local_naive().isoformat(),
        labs=usage_rows,
        totals=LaboratoryUsageTotals(
            laboratories_count=len(usage_rows),
            available_blocks=total_available_blocks,
            blocked_blocks=total_blocked_blocks,
            used_blocks=total_used_blocks,
            reserved_blocks=total_reserved_blocks,
            in_progress_blocks=total_in_progress_blocks,
            completed_blocks=total_completed_blocks,
            occupancy_percentage=_round_percentage(total_used_blocks, total_available_blocks),
        ),
        hourly_usage=hourly_usage,
        weekday_usage=weekday_usage,
        highest_usage_laboratory=usage_rows[0] if usage_rows else None,
        lowest_usage_laboratory=usage_rows[-1] if usage_rows else None,
    )
