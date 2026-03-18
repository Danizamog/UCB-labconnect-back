from pydantic import BaseModel
from typing import List, Literal


class DayReservationItemOut(BaseModel):
    start_time: str
    end_time: str
    status: Literal["occupied"]


class DayReservationsGroupOut(BaseModel):
    laboratory_id: int
    laboratory_name: str
    reservations: List[DayReservationItemOut]