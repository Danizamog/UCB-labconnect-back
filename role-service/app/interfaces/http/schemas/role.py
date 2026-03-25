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


class UserRoleNestedResponse(BaseModel):
    id: str
    nombre: str
    descripcion: str | None = None
    permisos: list[str] = Field(default_factory=list)


class UserWithRoleResponse(BaseModel):
    id: str
    name: str = ""
    email: str = ""
    roleId: str | None = None
    role: UserRoleNestedResponse | None = None
    created: str | None = None
    updated: str | None = None


class AssignUserRoleRequest(BaseModel):
    roleId: str | None = None
