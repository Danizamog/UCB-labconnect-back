from typing import List, Literal, Optional

from pydantic import BaseModel


class DayAvailabilityOut(BaseModel):
    day: int
    date: str
    status: Literal["available", "partial", "occupied"]
    occupied_slots: int
    total_slots: int


class LabCalendarOut(BaseModel):
    laboratory_id: int
    laboratory_name: str
    area_id: Optional[int] = None
    area_name: Optional[str] = None
    year: int
    month: int
    days: List[DayAvailabilityOut]