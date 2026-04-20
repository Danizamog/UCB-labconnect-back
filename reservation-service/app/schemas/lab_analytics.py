from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ANALYTICS_PERIODS = {"daily", "weekly", "monthly"}


class LaboratoryUsageStats(BaseModel):
    laboratory_id: str
    laboratory_name: str = ""
    laboratory_location: str = ""
    area_id: str = ""
    area_name: str = ""
    available_blocks: int
    blocked_blocks: int
    used_blocks: int
    reserved_blocks: int
    in_progress_blocks: int
    completed_blocks: int
    occupancy_percentage: float


class LaboratoryUsageTotals(BaseModel):
    laboratories_count: int
    available_blocks: int
    blocked_blocks: int
    used_blocks: int
    reserved_blocks: int
    in_progress_blocks: int
    completed_blocks: int
    occupancy_percentage: float


class LaboratoryUsageAnalyticsResponse(BaseModel):
    period: Literal["daily", "weekly", "monthly"]
    period_label: str
    start_date: str
    end_date: str
    generated_at: str
    labs: list[LaboratoryUsageStats]
    totals: LaboratoryUsageTotals
    highest_usage_laboratory: LaboratoryUsageStats | None = None
    lowest_usage_laboratory: LaboratoryUsageStats | None = None
