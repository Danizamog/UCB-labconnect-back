from dataclasses import dataclass


@dataclass
class StockItem:
    id: int
    name: str
    category: str
    unit: str
    quantity_available: float
    minimum_stock: float
    laboratory_id: int | None = None
    description: str | None = None
