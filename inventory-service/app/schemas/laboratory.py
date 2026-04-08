from __future__ import annotations
from pydantic import BaseModel, Field


class LaboratoryCreate(BaseModel):
    name: str
    location: str = ""
    capacity: int = 0
    description: str = ""
    is_active: bool = True
    area_id: str = ""
    allowed_roles: list[str] = Field(default_factory=list)
    allowed_user_ids: list[str] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)


class LaboratoryUpdate(BaseModel):
    name: str | None = None
    location: str | None = None
    capacity: int | None = None
    description: str | None = None
    is_active: bool | None = None
    area_id: str | None = None
    allowed_roles: list[str] | None = None
    allowed_user_ids: list[str] | None = None
    required_permissions: list[str] | None = None


class LaboratoryResponse(BaseModel):
    id: str
    name: str
    location: str
    capacity: int
    description: str
    is_active: bool
    area_id: str
    area_name: str | None = None
    allowed_roles: list[str] = Field(default_factory=list)
    allowed_user_ids: list[str] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    created: str
    updated: str
