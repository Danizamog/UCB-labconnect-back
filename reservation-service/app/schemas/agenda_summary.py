from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.lab_reservation import LabReservationResponse
from app.schemas.tutorial_session import TutorialSessionResponse


class AgendaSummaryResponse(BaseModel):
    generated_at: str
    reservation_count: int = 0
    tutorial_count: int = 0
    total_count: int = 0
    upcoming_reservations: list[LabReservationResponse] = Field(default_factory=list)
    upcoming_tutorials: list[TutorialSessionResponse] = Field(default_factory=list)