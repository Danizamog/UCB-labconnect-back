from pydantic import BaseModel
from typing import Optional


class AreaBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_active: bool = True


class AreaCreate(AreaBase):
    pass


class AreaUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class AreaOut(AreaBase):
    id: int

    model_config = {"from_attributes": True}