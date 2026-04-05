from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.application.container import loan_record_repo
from app.core.dependencies import ensure_any_permission, get_current_user
from app.schemas.loan_record import LoanDashboardResponse, LoanRecordCreate, LoanRecordResponse, LoanRecordReturn

router = APIRouter(prefix="/loans", tags=["loans"])
_MANAGE_LOANS = {"gestionar_prestamos", "gestionar_inventario", "gestionar_estado_equipos"}


@router.get("/dashboard", response_model=LoanDashboardResponse)
def get_loans_dashboard(current_user: dict = Depends(get_current_user)) -> LoanDashboardResponse:
    ensure_any_permission(current_user, _MANAGE_LOANS, "No tienes permisos para consultar prestamos")
    return loan_record_repo.get_dashboard()


@router.get("", response_model=list[LoanRecordResponse])
def list_loans(
    status_filter: str | None = Query(default=None, alias="status"),
    asset_id: str | None = Query(default=None),
    borrower_query: str | None = Query(default=None),
    serial_number: str | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
) -> list[LoanRecordResponse]:
    ensure_any_permission(current_user, _MANAGE_LOANS, "No tienes permisos para consultar prestamos")
    return loan_record_repo.list_all(
        status_filter=status_filter,
        asset_id=asset_id,
        borrower_query=borrower_query,
        serial_number=serial_number,
    )


@router.get("/assets/{asset_id}/history", response_model=list[LoanRecordResponse])
def list_asset_loan_history(asset_id: str, current_user: dict = Depends(get_current_user)) -> list[LoanRecordResponse]:
    ensure_any_permission(current_user, _MANAGE_LOANS, "No tienes permisos para consultar prestamos")
    return loan_record_repo.list_for_asset(asset_id)


@router.post("", response_model=LoanRecordResponse, status_code=status.HTTP_201_CREATED)
def create_loan(
    body: LoanRecordCreate,
    current_user: dict = Depends(get_current_user),
) -> LoanRecordResponse:
    ensure_any_permission(current_user, _MANAGE_LOANS, "No tienes permisos para registrar prestamos")
    try:
        return loan_record_repo.create(body, current_user=current_user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.patch("/{loan_id}/return", response_model=LoanRecordResponse)
@router.put("/{loan_id}/return", response_model=LoanRecordResponse)
def return_loan(
    loan_id: str,
    body: LoanRecordReturn,
    current_user: dict = Depends(get_current_user),
) -> LoanRecordResponse:
    ensure_any_permission(current_user, _MANAGE_LOANS, "No tienes permisos para registrar devoluciones")
    try:
        return loan_record_repo.return_loan(loan_id, body, current_user=current_user)
    except ValueError as exc:
        detail = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if "no encontrado" in detail.lower() else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code=status_code, detail=detail) from exc
