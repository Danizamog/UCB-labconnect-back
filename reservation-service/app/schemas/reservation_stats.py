from __future__ import annotations

from pydantic import BaseModel
from typing import List


class HourlyItem(BaseModel):
    hour: str
    count: int


class HourlyStatsResponse(BaseModel):
    laboratory_id: str | None = None
    area_id: str | None = None
    from_date: str
    to_date: str
    data: List[HourlyItem]


class TopSlotItem(BaseModel):
    slot: str
    count: int


class TopSlotsResponse(BaseModel):
    data: List[TopSlotItem]


class HeatmapResponse(BaseModel):
    days: List[str]
    hours: List[str]
    matrix: List[List[int]]
