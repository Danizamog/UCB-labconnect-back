from pydantic import BaseModel


class AssetCreate(BaseModel):
    name: str
    category: str
    description: str | None = None
    serial_number: str | None = None
    laboratory_id: int | None = None
    status: str = "available"


class AssetUpdate(AssetCreate):
    pass


class AssetStatusUpdate(BaseModel):
    status: str


class AssetOut(BaseModel):
    id: int
    name: str
    category: str
    description: str | None = None
    serial_number: str | None = None
    laboratory_id: int | None = None
    status: str


class StockItemCreate(BaseModel):
    name: str
    category: str
    unit: str
    quantity_available: float
    minimum_stock: float
    laboratory_id: int | None = None
    description: str | None = None


class StockItemUpdate(StockItemCreate):
    pass


class StockQuantityUpdate(BaseModel):
    quantity_available: float


class StockItemOut(BaseModel):
    id: int
    name: str
    category: str
    unit: str
    quantity_available: float
    minimum_stock: float
    laboratory_id: int | None = None
    description: str | None = None
