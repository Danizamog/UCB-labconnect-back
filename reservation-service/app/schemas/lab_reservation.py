from __future__ import annotations

from pydantic import BaseModel

RESERVATION_STATUSES = {"pending", "approved", "rejected", "cancelled", "in_progress", "completed", "absent"}


class LabReservationCreate(BaseModel):
    laboratory_id: str
    area_id: str = ""
    requested_by: str | None = None
    purpose: str = ""
    start_at: str
    end_at: str
    status: str | None = None
    attendees_count: int | None = None
    notes: str = ""
    approved_by: str | None = None
    approved_at: str | None = None
    cancel_reason: str = ""
    is_active: bool | None = None
    user_modification_count: int | None = None


class LabReservationUpdate(BaseModel):
    laboratory_id: str | None = None
    area_id: str | None = None
    requested_by: str | None = None
    purpose: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    status: str | None = None
    attendees_count: int | None = None
    notes: str | None = None
    approved_by: str | None = None
    approved_at: str | None = None
    cancel_reason: str | None = None
    is_active: bool | None = None
    user_modification_count: int | None = None


class LabReservationStatusUpdate(BaseModel):
    status: str
    cancel_reason: str | None = None


class LabReservationResponse(BaseModel):
    id: str
    laboratory_id: str
    area_id: str
    requested_by: str
    purpose: str
    start_at: str
    end_at: str
    status: str
    attendees_count: int | None = None
    notes: str
    approved_by: str
    approved_at: str
    cancel_reason: str
    is_active: bool
    created: str
    updated: str
    requested_by_name: str = ""
    requested_by_email: str = ""
    station_label: str = ""
    check_in_at: str = ""
    check_out_at: str = ""
    is_walk_in: bool = False
    user_modification_count: int = 0


class PaginatedLabReservationResponse(BaseModel):
    items: list[LabReservationResponse]
    pageNumber: int
    pageSize: int
    totalElements: int
    totalPages: int
    sortBy: str
    sortType: str
    where: str = ""


class LabReservationStatsResponse(BaseModel):
    total: int
    pending: int
    walk_in: int


class ReservationAccessUpdate(BaseModel):
    station_label: str = ""
    occupant_name: str = ""
    occupant_email: str = ""
    notes: str = ""


class WalkInReservationCreate(BaseModel):
    laboratory_id: str
    area_id: str = ""
    requested_by: str
    occupant_name: str
    occupant_email: str = ""
    purpose: str = ""
    start_at: str
    end_at: str
    station_label: str = ""
    notes: str = ""


class OccupancySessionResponse(BaseModel):
    reservation_id: str
    laboratory_id: str
    requested_by: str
    requested_by_name: str = ""
    requested_by_email: str = ""
    station_label: str = ""
    check_in_at: str
    start_at: str
    end_at: str
    is_walk_in: bool = False
    purpose: str = ""


class OccupancyLabSummary(BaseModel):
    laboratory_id: str
    occupancy_count: int


class OccupancyDashboardResponse(BaseModel):
    current_occupancy: int
    active_sessions: list[OccupancySessionResponse]
    lab_breakdown: list[OccupancyLabSummary]
