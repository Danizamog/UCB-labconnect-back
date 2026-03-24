from pydantic import BaseModel, Field


class RoleCreateRequest(BaseModel):
    nombre: str = Field(min_length=2, max_length=100)
    descripcion: str | None = Field(default=None)
    permisos: list[str] = Field(default_factory=list)


class RoleUpdateRequest(RoleCreateRequest):
    pass


class RoleResponse(BaseModel):
    id: str
    nombre: str
    descripcion: str | None = None
    permisos: list[str]
