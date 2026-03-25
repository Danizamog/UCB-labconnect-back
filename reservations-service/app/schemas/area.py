from pydantic import BaseModel, ConfigDict


class AreaBase(BaseModel):
    name: str
    description: str | None = None
    is_active: bool = True


class AreaCreate(AreaBase):
    pass


class AreaUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class AreaOut(AreaBase):
    id: int

    model_config = ConfigDict(from_attributes=True)
