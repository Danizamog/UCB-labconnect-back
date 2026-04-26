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



class UsageReportItem(BaseModel):
    asset_id: str
    asset_name: str
    borrower_id: str
    borrower_name: str
    practice: str
    quantity: int
    loaned_at: str
    returned_at: str | None = None

class UsageReportResponse(BaseModel):
    generated_at: str
    total_records: int
    items: list[UsageReportItem]

class StockReportResponse(BaseModel):
    generated_at: str
    total_items: int
    out_of_stock: int
    low_stock: int
    items: list[StockReportItem]
