from __future__ import annotations

from pydantic import BaseModel


class LabScheduleCreate(BaseModel):
    laboratory_id: str
    weekday: int
    open_time: str
    close_time: str
    slot_minutes: int | None = None
    is_active: bool | None = None


class LabScheduleUpdate(BaseModel):
    laboratory_id: str | None = None
    weekday: int | None = None
    open_time: str | None = None
    close_time: str | None = None
    slot_minutes: int | None = None
    is_active: bool | None = None


class LabScheduleResponse(BaseModel):
    id: str
    laboratory_id: str
    weekday: int
    open_time: str
    close_time: str
    slot_minutes: int
    is_active: bool
    created: str
    updated: str
