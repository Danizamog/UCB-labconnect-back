from pydantic import BaseModel, Field


class RoleCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=50)
    description: str | None = Field(default=None, max_length=250)
    permissions: list[str] = Field(default_factory=list)
    is_active: bool = True


class RoleUpdateRequest(RoleCreateRequest):
    pass


class RoleResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    permissions: list[str]
    is_active: bool
