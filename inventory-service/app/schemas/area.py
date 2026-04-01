from __future__ import annotations
from pydantic import BaseModel


class AreaCreate(BaseModel):
    name: str
    description: str = ""
    is_active: bool = True


class AreaUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class AreaResponse(BaseModel):
    id: str
    name: str
    description: str
    is_active: bool
    created: str
    updated: str
