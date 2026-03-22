from typing import Optional

from pydantic import BaseModel


class LaboratoryBase(BaseModel):
    name: str
    location: str
    capacity: int
    description: Optional[str] = None
    is_active: bool = True
    area_id: int


class LaboratoryCreate(LaboratoryBase):
    pass


class LaboratoryUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    capacity: Optional[int] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    area_id: Optional[int] = None


class LaboratoryOut(BaseModel):
    id: int
    name: str
    location: str
    capacity: int
    description: Optional[str] = None
    is_active: bool
    area_id: int
    area_name: Optional[str] = None

    model_config = {"from_attributes": True}