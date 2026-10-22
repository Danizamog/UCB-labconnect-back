from __future__ import annotations

from pydantic import BaseModel


class LabAccessSessionResponse(BaseModel):
    id: str
    reservation_id: str
    laboratory_id: str
    requested_by: str
    occupant_name: str = ""
    occupant_email: str = ""
    station_label: str = ""
    purpose: str = ""
    start_at: str
    end_at: str
    check_in_at: str
    check_out_at: str = ""
    status: str
    is_walk_in: bool = False
    recorded_by: str = ""
    notes: str = ""
    created: str = ""
    updated: str = ""
