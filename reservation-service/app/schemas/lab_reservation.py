from __future__ import annotations

from pydantic import BaseModel

RESERVATION_STATUSES = {"pending", "approved", "rejected", "cancelled"}


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
