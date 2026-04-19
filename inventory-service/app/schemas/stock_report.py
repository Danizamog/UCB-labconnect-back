from __future__ import annotations

from pydantic import BaseModel


class StockReportItem(BaseModel):
    item_id: str
    name: str
    category: str
    unit: str
    laboratory_id: str
    laboratory_name: str | None = None
    quantity_available: int
    minimum_stock: int
    status: str  # out_of_stock | low_stock | ok


class StockReportResponse(BaseModel):
    generated_at: str
    total_items: int
    out_of_stock: int
    low_stock: int
    items: list[StockReportItem]
