from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.dependencies import ensure_any_permission, get_current_user_payload, get_db
from app.infrastructure.pocketbase_sync import sync_inventory_to_pocketbase
from app.models.asset import Asset
from app.models.loan_record import LoanRecord
from app.models.stock_item import StockItem
from app.schemas.loan import (
    LoanBreakdownOut,
    LoanCreate,
    LoanDashboardOut,
    LoanRecordOut,
    LoanReturnPayload,
    LoanStockAlertOut,
    LoanTrendPointOut,
)
from app.services.stock_movements import apply_stock_change

router = APIRouter(prefix="/loans", tags=["loans"])

READ_PERMISSIONS = {"gestionar_prestamos", "generar_reportes", "consultar_estadisticas"}
WRITE_PERMISSIONS = {"gestionar_prestamos"}


def utcnow() -> datetime:
    return datetime.utcnow()


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)


def get_display_status(loan: LoanRecord, now: datetime | None = None) -> str:
    reference_time = now or utcnow()
    if loan.status == "active" and loan.due_at < reference_time:
        return "overdue"
    return loan.status


def serialize_loan(loan: LoanRecord, now: datetime | None = None) -> LoanRecordOut:
    return LoanRecordOut(
        id=loan.id,
        loan_type=loan.loan_type,
        source_type=loan.source_type,
        practice_request_id=loan.practice_request_id,
        asset_id=loan.asset_id,
        stock_item_id=loan.stock_item_id,
        laboratory_id=loan.laboratory_id,
        item_name=loan.item_name,
        item_category=loan.item_category,
        borrower_name=loan.borrower_name,
        borrower_email=loan.borrower_email,
        borrower_role=loan.borrower_role,
        purpose=loan.purpose,
        quantity=loan.quantity,
        status=get_display_status(loan, now),
        raw_status=loan.status,
        return_condition=loan.return_condition,
        notes=loan.notes,
        return_notes=loan.return_notes,
        incident_notes=loan.incident_notes,
        approved_by=loan.approved_by,
        returned_by=loan.returned_by,
        loaned_at=loan.loaned_at,
        due_at=loan.due_at,
        returned_at=loan.returned_at,
    )


def require_read_access(current_user: dict) -> None:
    ensure_any_permission(current_user, READ_PERMISSIONS, "No autorizado para ver prestamos y reportes")


def require_write_access(current_user: dict) -> None:
    ensure_any_permission(current_user, WRITE_PERMISSIONS, "No autorizado para gestionar prestamos")


def validate_due_at(due_at: datetime) -> None:
    if normalize_datetime(due_at) <= utcnow():
        raise HTTPException(status_code=400, detail="La fecha limite de devolucion debe estar en el futuro")


@router.get("/dashboard", response_model=LoanDashboardOut)
def get_loans_dashboard(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    require_read_access(current_user)

    loans = db.query(LoanRecord).order_by(LoanRecord.loaned_at.desc()).all()
    materials_on_alert = (
        db.query(StockItem)
        .filter(StockItem.quantity_available <= StockItem.minimum_stock)
        .order_by(StockItem.quantity_available.asc(), StockItem.name.asc())
        .limit(5)
        .all()
    )

    now = utcnow()
    today = now.date()
    active_loans = [loan for loan in loans if loan.status == "active"]
    display_status_counter = Counter(get_display_status(loan, now) for loan in loans)
    active_type_counter = Counter(loan.loan_type for loan in active_loans)

    trend_lookup: dict[str, int] = {}
    start_window = today - timedelta(days=6)
    for index in range(7):
        current_day = start_window + timedelta(days=index)
        trend_lookup[current_day.isoformat()] = 0
    for loan in loans:
        loan_date = loan.loaned_at.date().isoformat()
        if loan_date in trend_lookup:
            trend_lookup[loan_date] += 1

    returned_this_month = sum(
        1
        for loan in loans
        if loan.status == "returned"
        and loan.returned_at is not None
        and loan.returned_at.year == now.year
        and loan.returned_at.month == now.month
    )

    overdue_count = sum(1 for loan in active_loans if loan.due_at.date() < today)
    due_today_count = sum(1 for loan in active_loans if loan.due_at.date() == today)

    return LoanDashboardOut(
        total_active=len(active_loans),
        overdue_count=overdue_count,
        due_today_count=due_today_count,
        returned_this_month=returned_this_month,
        asset_loans_active=active_type_counter.get("asset", 0),
        material_loans_active=active_type_counter.get("material", 0),
        low_stock_materials=len(materials_on_alert),
        status_breakdown=[
            LoanBreakdownOut(label=label, value=value)
            for label, value in sorted(display_status_counter.items())
        ],
        type_breakdown=[
            LoanBreakdownOut(label=label, value=value)
            for label, value in sorted(active_type_counter.items())
        ],
        loan_trend=[
            LoanTrendPointOut(date=trend_date, value=value)
            for trend_date, value in trend_lookup.items()
        ],
        recent_loans=[serialize_loan(loan, now) for loan in loans[:6]],
        low_stock_alerts=[LoanStockAlertOut.model_validate(item) for item in materials_on_alert],
    )


@router.get("/", response_model=list[LoanRecordOut])
def list_loans(
    status_filter: str | None = Query(default=None, alias="status"),
    loan_type: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    practice_request_id: int | None = Query(default=None),
    search: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    require_read_access(current_user)

    query = db.query(LoanRecord).order_by(LoanRecord.loaned_at.desc())

    if loan_type in {"asset", "material"}:
        query = query.filter(LoanRecord.loan_type == loan_type)
    if source_type in {"manual", "practice_request"}:
        query = query.filter(LoanRecord.source_type == source_type)
    if practice_request_id is not None:
        query = query.filter(LoanRecord.practice_request_id == practice_request_id)

    if search:
        search_value = f"%{search.strip()}%"
        query = query.filter(
            or_(
                LoanRecord.item_name.ilike(search_value),
                LoanRecord.borrower_name.ilike(search_value),
                LoanRecord.borrower_email.ilike(search_value),
                LoanRecord.purpose.ilike(search_value),
            )
        )

    loans = query.all()
    now = utcnow()

    if status_filter in {"active", "returned", "overdue"}:
        loans = [loan for loan in loans if get_display_status(loan, now) == status_filter]

    return [serialize_loan(loan, now) for loan in loans]


@router.post("/", response_model=LoanRecordOut, status_code=status.HTTP_201_CREATED)
def create_loan(
    payload: LoanCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    require_write_access(current_user)
    due_at = normalize_datetime(payload.due_at)
    validate_due_at(due_at)

    if payload.loan_type == "asset":
        if payload.asset_id is None:
            raise HTTPException(status_code=400, detail="Selecciona un equipo para registrar el prestamo")
        if payload.quantity != 1:
            raise HTTPException(status_code=400, detail="Los prestamos de equipos solo admiten cantidad 1")

        asset = db.query(Asset).filter(Asset.id == payload.asset_id).first()
        if not asset:
            raise HTTPException(status_code=404, detail="Equipo no encontrado")
        if asset.status != "available":
            raise HTTPException(status_code=400, detail="El equipo seleccionado no esta disponible para prestamo")

        asset.status = "loaned"
        item_name = asset.name
        item_category = asset.category
        laboratory_id = asset.laboratory_id
        asset_id = asset.id
        stock_item_id = None
    else:
        if payload.stock_item_id is None:
            raise HTTPException(status_code=400, detail="Selecciona un material para registrar el prestamo")

        material = db.query(StockItem).filter(StockItem.id == payload.stock_item_id).first()
        if not material:
            raise HTTPException(status_code=404, detail="Material no encontrado")
        if payload.affect_stock and payload.quantity > material.quantity_available:
            raise HTTPException(
                status_code=400,
                detail="La cantidad solicitada supera el stock disponible del material",
            )

        if payload.affect_stock:
            apply_stock_change(
                db,
                material,
                quantity_change=-payload.quantity,
                movement_type="loan_issue",
                performed_by=current_user.get("username") or "system",
                notes=f"Salida por prestamo para {payload.borrower_name.strip()}",
                reference_type=payload.source_type,
                reference_id=payload.practice_request_id,
            )
        item_name = material.name
        item_category = material.category
        laboratory_id = material.laboratory_id
        asset_id = None
        stock_item_id = material.id

    record = LoanRecord(
        loan_type=payload.loan_type,
        source_type=payload.source_type,
        practice_request_id=payload.practice_request_id,
        asset_id=asset_id,
        stock_item_id=stock_item_id,
        laboratory_id=laboratory_id,
        item_name=item_name,
        item_category=item_category,
        borrower_name=payload.borrower_name.strip(),
        borrower_email=payload.borrower_email.strip().lower(),
        borrower_role=payload.borrower_role.strip(),
        purpose=payload.purpose.strip(),
        quantity=payload.quantity,
        status="active",
        return_condition=None,
        notes=payload.notes.strip() if payload.notes else None,
        approved_by=current_user.get("username"),
        loaned_at=utcnow(),
        due_at=due_at,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    sync_inventory_to_pocketbase()
    return serialize_loan(record, utcnow())


@router.patch("/{loan_id}/return", response_model=LoanRecordOut)
def return_loan(
    loan_id: int,
    payload: LoanReturnPayload,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    require_write_access(current_user)

    record = db.query(LoanRecord).filter(LoanRecord.id == loan_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Prestamo no encontrado")
    if record.status != "active":
        raise HTTPException(status_code=400, detail="Solo se pueden devolver prestamos activos")

    if record.loan_type == "asset" and record.asset_id is not None:
        asset = db.query(Asset).filter(Asset.id == record.asset_id).first()
        if asset and asset.status == "loaned":
            asset.status = "available"
    elif record.loan_type == "material" and record.stock_item_id is not None:
        material = db.query(StockItem).filter(StockItem.id == record.stock_item_id).first()
        if material:
            apply_stock_change(
                db,
                material,
                quantity_change=record.quantity,
                movement_type="loan_return",
                performed_by=current_user.get("username") or "system",
                notes=payload.return_notes or payload.incident_notes,
                reference_type=record.source_type,
                reference_id=record.id,
            )

    record.status = "returned"
    record.returned_at = utcnow()
    record.returned_by = current_user.get("username")
    record.return_condition = payload.return_condition
    record.return_notes = payload.return_notes.strip() if payload.return_notes else None
    record.incident_notes = payload.incident_notes.strip() if payload.incident_notes else None

    db.commit()
    db.refresh(record)
    sync_inventory_to_pocketbase()
    return serialize_loan(record, record.returned_at)
