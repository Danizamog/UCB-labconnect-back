from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from app.application.container import stock_item_repo, loan_record_repo
from app.core.dependencies import get_current_user
from app.schemas.stock_report import StockReportItem, StockReportResponse, UsageReportItem, UsageReportResponse
router = APIRouter(prefix="/reports", tags=["reports"])

@router.get("/usage", response_model=UsageReportResponse)
def get_usage_report(
    borrower_id: str | None = Query(default=None),
    practice: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    _: dict = Depends(get_current_user),
) -> UsageReportResponse:
    """
    Reporte de uso de insumos agrupado por práctica y usuario.
    Filtros opcionales: usuario, práctica, rango de fechas (prestamo).
    """
    records = loan_record_repo.list_all()
    items: list[UsageReportItem] = []
    for r in records:
        # Filtros
        if borrower_id and r.borrower_id != borrower_id:
            continue
        if practice and (r.purpose or "").lower() != practice.lower():
            continue
        if date_from and r.loaned_at < date_from:
            continue
        if date_to and r.loaned_at > date_to:
            continue
        items.append(
            UsageReportItem(
                asset_id=r.asset_id,
                asset_name=r.asset_name,
                borrower_id=r.borrower_id,
                borrower_name=r.borrower_name,
                practice=r.purpose or "",
                quantity=1,  # Asumimos 1 por registro (ajustar si hay campo de cantidad)
                loaned_at=r.loaned_at,
                returned_at=r.returned_at if hasattr(r, "returned_at") else None,
            )
        )
    return UsageReportResponse(
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_records=len(items),
        items=items,
    )



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
    _: dict = Depends(get_current_user),
) -> StockReportResponse:
    items = stock_item_repo.list_all()

    report_items: list[StockReportItem] = []
    for item in items:
        if laboratory_id and str(item.laboratory_id or "") != laboratory_id:
            continue

        status = _stock_status(item.quantity_available, item.minimum_stock)
        if only_low_or_out and status == "ok":
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

    out_of_stock = sum(1 for item in report_items if item.status == "out_of_stock")
    low_stock = sum(1 for item in report_items if item.status == "low_stock")

    return StockReportResponse(
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_items=len(report_items),
        out_of_stock=out_of_stock,
        low_stock=low_stock,
        items=report_items,
    )
