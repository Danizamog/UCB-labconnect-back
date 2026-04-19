from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.application.container import stock_item_repo
from app.core.dependencies import get_current_user
from app.schemas.stock_report import StockReportItem, StockReportResponse

router = APIRouter(prefix="/reports", tags=["reports"])


def _stock_status(quantity_available: int, minimum_stock: int) -> str:
    if quantity_available <= 0:
        return "out_of_stock"
    if quantity_available <= max(0, minimum_stock):
        return "low_stock"
    return "ok"


@router.get("/stock-items", response_model=StockReportResponse)
def get_stock_items_report(
    laboratory_id: str | None = Query(default=None),
    only_low_or_out: bool = Query(default=False),
    status_filter: Literal["out_of_stock", "low_stock", "ok"] | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1, max_length=80),
    _: dict = Depends(get_current_user),
) -> StockReportResponse:
    items = stock_item_repo.list_all()
    normalized_search = (search or "").strip().lower()

    report_items: list[StockReportItem] = []
    for item in items:
        if laboratory_id and str(item.laboratory_id or "") != laboratory_id:
            continue

        if normalized_search:
            searchable_values = " ".join(
                [
                    str(item.name or ""),
                    str(item.category or ""),
                    str(item.laboratory_name or ""),
                ]
            ).lower()
            if normalized_search not in searchable_values:
                continue

        status = _stock_status(item.quantity_available, item.minimum_stock)
        if only_low_or_out and status == "ok":
            continue
        if status_filter and status != status_filter:
            continue

        report_items.append(
            StockReportItem(
                item_id=item.id,
                name=item.name,
                category=item.category,
                unit=item.unit,
                laboratory_id=item.laboratory_id,
                laboratory_name=item.laboratory_name,
                quantity_available=item.quantity_available,
                minimum_stock=item.minimum_stock,
                status=status,
            )
        )

    status_order = {"out_of_stock": 0, "low_stock": 1, "ok": 2}
    report_items.sort(key=lambda item: (status_order.get(item.status, 99), item.name.lower()))

    out_of_stock = sum(1 for item in report_items if item.status == "out_of_stock")
    low_stock = sum(1 for item in report_items if item.status == "low_stock")

    return StockReportResponse(
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_items=len(report_items),
        out_of_stock=out_of_stock,
        low_stock=low_stock,
        items=report_items,
    )
