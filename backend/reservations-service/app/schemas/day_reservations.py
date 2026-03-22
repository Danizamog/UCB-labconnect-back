from typing import List, Literal, Optional

from pydantic import BaseModel


class DayReservationItemOut(BaseModel):
    start_time: str
    end_time: str
    status: Literal["occupied"]


class DayReservationsGroupOut(BaseModel):
    laboratory_id: int
    laboratory_name: str
    area_id: Optional[int] = None
    area_name: Optional[str] = None
    reservations: List[DayReservationItemOut]