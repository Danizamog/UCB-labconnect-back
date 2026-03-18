from datetime import date, time, datetime
from typing import List, Optional

from pydantic import BaseModel


class PracticeMaterialItem(BaseModel):
    asset_id: int
    quantity: int


class PracticeRequestCreate(BaseModel):
    laboratory_id: int
    date: date
    start_time: time
    end_time: time
    materials: List[PracticeMaterialItem]
    needs_support: bool = False
    support_topic: Optional[str] = None
    notes: Optional[str] = None


class PracticeMaterialOut(BaseModel):
    id: int
    asset_id: int
    material_name: str
    quantity: int

    model_config = {"from_attributes": True}


class PracticeRequestOut(BaseModel):
    id: int
    user_id: int
    username: str
    laboratory_id: int
    laboratory_name: str
    date: date
    start_time: time
    end_time: time
    needs_support: bool
    support_topic: Optional[str] = None
    notes: Optional[str] = None
    status: str
    created_at: datetime
    materials: List[PracticeMaterialOut]

    model_config = {"from_attributes": True}