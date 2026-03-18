from pydantic import BaseModel
from typing import List, Literal


class DayAvailabilityOut(BaseModel):
    day: int
    date: str
    status: Literal["available", "occupied", "partial"]
    occupied_slots: int
    total_slots: int


class LabCalendarOut(BaseModel):
    laboratory_id: int
    laboratory_name: str
    year: int
    month: int
    days: List[DayAvailabilityOut]