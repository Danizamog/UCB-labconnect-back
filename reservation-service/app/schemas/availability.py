from __future__ import annotations

from pydantic import BaseModel


class AvailabilitySlot(BaseModel):
    start_time: str
    end_time: str
    state: str
    source: str = ""
    source_id: str = ""
    status: str = ""


class LabAvailabilityResponse(BaseModel):
    laboratory_id: str
    date: str
    slot_minutes: int
    slots: list[AvailabilitySlot]


class LabOccupancyResponse(BaseModel):
    laboratory_id: str
    laboratory_name: str
    area_id: str = ""
    capacity: int
    current_occupancy: int
    available_slots: int
    occupancy_percentage: float
    status: str
