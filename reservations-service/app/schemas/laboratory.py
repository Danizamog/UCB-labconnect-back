from pydantic import BaseModel, ConfigDict


class LaboratoryBase(BaseModel):
    name: str
    location: str
    capacity: int
    description: str | None = None
    is_active: bool = True
    area_id: int


class LaboratoryCreate(LaboratoryBase):
    pass


class LaboratoryUpdate(BaseModel):
    name: str | None = None
    location: str | None = None
    capacity: int | None = None
    description: str | None = None
    is_active: bool | None = None
    area_id: int | None = None


class LaboratoryOut(BaseModel):
    id: int
    name: str
    location: str
    capacity: int
    description: str | None = None
    is_active: bool = True
    area_id: int
    area_name: str | None = None

    model_config = ConfigDict(from_attributes=True)
