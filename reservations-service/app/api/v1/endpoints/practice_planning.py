from collections import defaultdict
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.core.dependencies import ensure_any_permission, get_current_user_payload, get_db
from app.infrastructure.inventory_client import (
    close_material_loan,
    InventoryServiceError,
    create_material_loan_from_practice,
    list_material_catalog,
    list_practice_material_loans,
    release_material_from_practice,
    reserve_material_from_practice,
)
from app.infrastructure.pocketbase_sync import sync_practice_materials_to_pocketbase, sync_practice_requests_to_pocketbase
from app.models.laboratory import Laboratory
from app.models.practice_material import PracticeMaterial
from app.models.practice_request import PracticeRequest
from app.realtime.events import publish_reservations_event
from app.schemas.practice_request import PracticeRequestCreate, PracticeRequestResponse, ReservationNotification
from app.schemas.reservation_status import PracticeStatusUpdate


router = APIRouter(prefix="/practice-planning", tags=["practice-planning"])


def get_material_catalog_index() -> dict[int, dict]:
    try:
        catalog = list_material_catalog()
    except InventoryServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        int(item["id"]): item
        for item in catalog
        if isinstance(item, dict) and item.get("id") is not None
    }


def list_linked_loans_map(practice_ids: list[int] | None = None) -> dict[int, list[dict]]:
    try:
        loans = list_practice_material_loans()
    except InventoryServiceError:
        return {}

    selected_ids = set(practice_ids or [])
    grouped: dict[int, list[dict]] = defaultdict(list)
    for loan in loans:
        if not isinstance(loan, dict):
            continue
        practice_request_id = loan.get("practice_request_id")
        if practice_request_id is None:
            continue
        normalized_id = int(practice_request_id)
        if selected_ids and normalized_id not in selected_ids:
            continue
        grouped[normalized_id].append(loan)
    return grouped


def summarize_material_tracking(loans: list[dict], has_materials: bool, reservation_status: str) -> str | None:
    if not has_materials:
        return None
    if reservation_status == "pending" and not loans:
        return "Stock reservado"
    if reservation_status in {"rejected", "cancelled"} and not loans:
        return "Seguimiento cerrado"
    if reservation_status == "approved" and not loans:
        return "Preparando seguimiento"
    if any(str(loan.get("status")) in {"active", "overdue"} for loan in loans):
        return "Pendiente de devolucion"
    if any(loan.get("return_condition") == "issues" for loan in loans):
        return "Devuelto con observaciones"
    if loans and all(str(loan.get("status")) == "returned" for loan in loans):
        return "Devuelto correctamente"
    return "En seguimiento"


def serialize_practice(practice: PracticeRequest, linked_loans: list[dict] | None = None) -> PracticeRequestResponse:
    loans = linked_loans or []
    return PracticeRequestResponse(
        id=practice.id,
        user_id=practice.user_id,
        username=practice.username,
        subject_name=practice.subject_name,
        laboratory_id=practice.laboratory_id,
        laboratory_name=practice.laboratory.name if practice.laboratory else "Laboratorio desconocido",
        date=practice.date,
        start_time=practice.start_time,
        end_time=practice.end_time,
        needs_support=practice.needs_support,
        support_topic=practice.support_topic,
        notes=practice.notes,
        review_comment=practice.review_comment,
        status=practice.status,
        created_at=practice.created_at,
        status_updated_at=practice.status_updated_at,
        user_notification_read=practice.user_notification_read,
        material_tracking_status=summarize_material_tracking(loans, bool(practice.materials), practice.status),
        materials=[
            {
                "id": material.id,
                "asset_id": material.asset_id,
                "material_name": material.material_name,
                "quantity": material.quantity,
            }
            for material in practice.materials
        ],
        material_loans=[
            {
                "loan_id": int(loan.get("id")),
                "material_name": loan.get("item_name") or "Material",
                "quantity": int(loan.get("quantity") or 0),
                "status": str(loan.get("status") or "active"),
                "return_condition": loan.get("return_condition"),
                "return_notes": loan.get("return_notes"),
                "incident_notes": loan.get("incident_notes"),
                "due_at": loan.get("due_at"),
            }
            for loan in loans
        ],
    )


def validate_materials_availability(
    db: Session,
    payload: PracticeRequestCreate,
) -> dict[int, dict]:
    catalog_by_id = get_material_catalog_index()

    for material in payload.materials:
        if material.quantity <= 0:
            raise HTTPException(status_code=400, detail="La cantidad solicitada de materiales debe ser mayor a 0")

        catalog_item = catalog_by_id.get(material.asset_id)
        if not catalog_item:
            raise HTTPException(status_code=400, detail="Uno de los materiales seleccionados no existe")

        material_lab_id = catalog_item.get("laboratory_id")
        if material_lab_id is not None and int(material_lab_id) != payload.laboratory_id:
            raise HTTPException(
                status_code=400,
                detail=f"El material {catalog_item.get('name', material.asset_id)} no pertenece al laboratorio seleccionado",
            )

        available_quantity = int(catalog_item.get("quantity_available") or 0)

        if material.quantity > available_quantity:
            raise HTTPException(
                status_code=409,
                detail=f"No hay stock suficiente para {catalog_item.get('name', 'el material solicitado')}",
            )

    return catalog_by_id


def reserve_material_stock(practice: PracticeRequest, current_user: dict) -> None:
    borrower_name = current_user.get("name") or practice.username
    reserved_materials: list[PracticeMaterial] = []

    try:
        for material in practice.materials:
            reserve_material_from_practice(
                {
                    "practice_request_id": practice.id,
                    "stock_item_id": material.asset_id,
                    "quantity": material.quantity,
                    "notes": f"Stock reservado automaticamente para la solicitud #{practice.id} de {borrower_name}",
                }
            )
            reserved_materials.append(material)
    except InventoryServiceError:
        for reserved_material in reserved_materials:
            try:
                release_material_from_practice(
                    {
                        "practice_request_id": practice.id,
                        "stock_item_id": reserved_material.asset_id,
                        "quantity": reserved_material.quantity,
                        "notes": f"Compensacion automatica por fallo al reservar la solicitud #{practice.id}",
                    }
                )
            except InventoryServiceError:
                pass
        raise


def release_material_stock(practice: PracticeRequest, status: str) -> None:
    for material in practice.materials:
        release_material_from_practice(
            {
                "practice_request_id": practice.id,
                "stock_item_id": material.asset_id,
                "quantity": material.quantity,
                "notes": f"Stock liberado automaticamente porque la solicitud #{practice.id} fue {status}",
            }
        )


def register_material_tracking(practice: PracticeRequest, current_user: dict) -> list[dict]:
    existing_loans = list_linked_loans_map([practice.id]).get(practice.id, [])
    existing_material_ids = {
        int(loan.get("stock_item_id"))
        for loan in existing_loans
        if loan.get("stock_item_id") is not None
    }

    created_loans: list[dict] = []
    practice_end_at = datetime.combine(practice.date, practice.end_time)
    fallback_due_at = datetime.utcnow() + timedelta(hours=2)
    due_at = max(practice_end_at + timedelta(hours=2), fallback_due_at)
    borrower_name = current_user.get("name") or practice.username

    for material in practice.materials:
        if material.asset_id in existing_material_ids:
            continue

        created_loans.append(
            create_material_loan_from_practice(
                {
                    "loan_type": "material",
                    "source_type": "practice_request",
                    "practice_request_id": practice.id,
                    "stock_item_id": material.asset_id,
                    "borrower_name": borrower_name,
                    "borrower_email": practice.username,
                    "borrower_role": "Usuario",
                    "purpose": f"Reserva aprobada #{practice.id} de {practice.subject_name or 'practica'} para {practice.laboratory.name if practice.laboratory else 'laboratorio'}",
                    "quantity": material.quantity,
                    "due_at": due_at.isoformat(),
                    "notes": f"Seguimiento automatico generado desde la reserva #{practice.id}",
                    "affect_stock": False,
                }
            )
        )

    return existing_loans + created_loans


def close_material_tracking(practice_id: int, status: str) -> list[dict]:
    existing_loans = list_linked_loans_map([practice_id]).get(practice_id, [])
    closed_loans: list[dict] = []

    for loan in existing_loans:
        if str(loan.get("raw_status") or loan.get("status")) != "active":
            closed_loans.append(loan)
            continue

        closed_loans.append(
            close_material_loan(
                int(loan["id"]),
                "cancelled",
                f"Seguimiento cerrado automaticamente porque la reserva fue {status}.",
            )
        )

    return closed_loans


@router.post("/", response_model=PracticeRequestResponse)
def create_practice_planning(
    payload: PracticeRequestCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    today = date.today()
    max_allowed_date = today + timedelta(days=30)

    if payload.date < today:
        raise HTTPException(status_code=400, detail="No puedes reservar en una fecha pasada")
    if payload.date > max_allowed_date:
        raise HTTPException(status_code=400, detail="Solo puedes reservar dentro de los proximos 30 dias")
    if payload.start_time < time(7, 0) or payload.start_time > time(21, 0):
        raise HTTPException(status_code=400, detail="La hora de inicio debe estar entre 07:00 y 21:00")
    if payload.end_time < time(7, 0) or payload.end_time > time(21, 0):
        raise HTTPException(status_code=400, detail="La hora de fin debe estar entre 07:00 y 21:00")
    if payload.start_time >= payload.end_time:
        raise HTTPException(status_code=400, detail="La hora de inicio debe ser menor que la hora de fin")
    if not payload.subject_name or not payload.subject_name.strip():
        raise HTTPException(status_code=400, detail="La materia o asignatura es obligatoria")
    if not payload.notes or not payload.notes.strip():
        raise HTTPException(status_code=400, detail="Las observaciones son obligatorias")
    if payload.needs_support and (not payload.support_topic or not payload.support_topic.strip()):
        raise HTTPException(status_code=400, detail="Debes indicar el tipo de apoyo requerido")

    laboratory = db.query(Laboratory).filter(Laboratory.id == payload.laboratory_id).first()
    if not laboratory:
        raise HTTPException(status_code=404, detail="Laboratorio no encontrado")
    if not laboratory.is_active:
        raise HTTPException(status_code=400, detail="El laboratorio seleccionado no esta activo")

    overlapping = (
        db.query(PracticeRequest)
        .filter(
            PracticeRequest.laboratory_id == payload.laboratory_id,
            PracticeRequest.date == payload.date,
            PracticeRequest.start_time < payload.end_time,
            PracticeRequest.end_time > payload.start_time,
            PracticeRequest.status.in_(["pending", "approved"]),
        )
        .first()
    )

    if overlapping:
        raise HTTPException(status_code=409, detail="El laboratorio ya esta reservado en ese horario")

    catalog_by_id = validate_materials_availability(db, payload) if payload.materials else {}

    practice = PracticeRequest(
        user_id=current_user["user_id"],
        username=current_user["username"],
        subject_name=payload.subject_name.strip(),
        laboratory_id=payload.laboratory_id,
        date=payload.date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        needs_support=payload.needs_support,
        support_topic=payload.support_topic,
        notes=payload.notes.strip(),
        review_comment=None,
        status="pending",
        status_updated_at=datetime.utcnow(),
        user_notification_read=True,
    )

    db.add(practice)
    db.flush()

    for material in payload.materials:
        catalog_item = catalog_by_id.get(material.asset_id, {})
        material_name = material.material_name or catalog_item.get("name") or f"Material {material.asset_id}"
        db.add(
            PracticeMaterial(
                practice_request_id=practice.id,
                asset_id=material.asset_id,
                material_name=material_name,
                quantity=material.quantity,
            )
        )

    db.flush()

    try:
        practice = (
            db.query(PracticeRequest)
            .options(joinedload(PracticeRequest.laboratory), joinedload(PracticeRequest.materials))
            .filter(PracticeRequest.id == practice.id)
            .first()
        )

        if practice and practice.materials:
            reserve_material_stock(practice, current_user)

        db.commit()
    except InventoryServiceError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise

    practice = (
        db.query(PracticeRequest)
        .options(joinedload(PracticeRequest.laboratory), joinedload(PracticeRequest.materials))
        .filter(PracticeRequest.id == practice.id)
        .first()
    )
    sync_practice_requests_to_pocketbase()
    sync_practice_materials_to_pocketbase()
    publish_reservations_event(
        "practice_request.created",
        "practice_request",
        {
            "practice_request_id": practice.id,
            "laboratory_id": practice.laboratory_id,
            "date": practice.date.isoformat(),
            "status": practice.status,
        },
    )
    return serialize_practice(practice)


@router.get("/my", response_model=list[PracticeRequestResponse])
def get_my_practice_plannings(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    practices = (
        db.query(PracticeRequest)
        .options(joinedload(PracticeRequest.laboratory), joinedload(PracticeRequest.materials))
        .filter(PracticeRequest.user_id == current_user["user_id"])
        .order_by(PracticeRequest.created_at.desc())
        .all()
    )
    linked_loans_map = list_linked_loans_map([practice.id for practice in practices])
    return [serialize_practice(practice, linked_loans_map.get(practice.id, [])) for practice in practices]


@router.get("/my/notifications", response_model=list[ReservationNotification])
def get_my_notifications(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    practices = (
        db.query(PracticeRequest)
        .options(joinedload(PracticeRequest.laboratory))
        .filter(
            PracticeRequest.user_id == current_user["user_id"],
            PracticeRequest.status != "pending",
        )
        .order_by(PracticeRequest.status_updated_at.desc())
        .all()
    )
    return [
        ReservationNotification(
            id=practice.id,
            title=f"Solicitud {practice.status}",
            message=f"Tu reserva de {practice.subject_name or 'practica'} para {practice.laboratory.name if practice.laboratory else 'el laboratorio'} fue {practice.status}. Revisa el seguimiento de materiales en Mis reservas.",
            status=practice.status,
            review_comment=practice.review_comment,
            created_at=practice.status_updated_at,
            read=practice.user_notification_read,
            laboratory_name=practice.laboratory.name if practice.laboratory else "Laboratorio",
            date=practice.date,
            start_time=practice.start_time,
            end_time=practice.end_time,
        )
        for practice in practices
    ]


@router.patch("/{practice_id}/notifications/read")
def mark_notification_as_read(
    practice_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    practice = (
        db.query(PracticeRequest)
        .filter(
            PracticeRequest.id == practice_id,
            PracticeRequest.user_id == current_user["user_id"],
        )
        .first()
    )
    if not practice:
        raise HTTPException(status_code=404, detail="Reserva no encontrada")

    practice.user_notification_read = True
    db.commit()
    sync_practice_requests_to_pocketbase()
    return {"ok": True}


@router.get("/", response_model=list[PracticeRequestResponse])
def get_all_practice_plannings(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_any_permission(current_user, {"gestionar_reservas"}, "No autorizado para ver las reservas")
    practices = (
        db.query(PracticeRequest)
        .options(joinedload(PracticeRequest.laboratory), joinedload(PracticeRequest.materials))
        .order_by(PracticeRequest.created_at.desc())
        .all()
    )
    linked_loans_map = list_linked_loans_map([practice.id for practice in practices])
    return [serialize_practice(practice, linked_loans_map.get(practice.id, [])) for practice in practices]


@router.patch("/{practice_id}/status", response_model=PracticeRequestResponse)
def update_practice_status(
    practice_id: int,
    payload: PracticeStatusUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_any_permission(current_user, {"gestionar_reservas"}, "No autorizado para actualizar reservas")

    allowed_status = {"approved", "rejected", "cancelled", "pending"}
    if payload.status not in allowed_status:
        raise HTTPException(status_code=400, detail="Estado invalido")

    practice = (
        db.query(PracticeRequest)
        .options(joinedload(PracticeRequest.laboratory), joinedload(PracticeRequest.materials))
        .filter(PracticeRequest.id == practice_id)
        .first()
    )
    if not practice:
        raise HTTPException(status_code=404, detail="Reserva no encontrada")

    previous_status = practice.status
    practice.status = payload.status
    practice.review_comment = payload.review_comment
    practice.status_updated_at = datetime.utcnow()
    practice.user_notification_read = False
    db.commit()

    linked_loans: list[dict] = []
    if payload.status == "approved" and practice.materials and previous_status != "approved":
        try:
            if previous_status in {"rejected", "cancelled"}:
                reserve_material_stock(practice, current_user)
            linked_loans = register_material_tracking(practice, current_user)
        except InventoryServiceError as exc:
            practice.status = "pending"
            practice.review_comment = "No se pudo aprobar porque fallo el seguimiento automatico de materiales."
            practice.status_updated_at = datetime.utcnow()
            practice.user_notification_read = False
            db.commit()
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    elif practice.materials and payload.status in {"rejected", "cancelled"} and previous_status not in {"rejected", "cancelled"}:
        try:
            existing_loans = list_linked_loans_map([practice.id]).get(practice.id, [])
            if existing_loans:
                linked_loans = close_material_tracking(practice.id, payload.status)
            else:
                release_material_stock(practice, payload.status)
                linked_loans = []
        except InventoryServiceError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    elif practice.materials and payload.status == "pending" and previous_status in {"rejected", "cancelled"}:
        try:
            reserve_material_stock(practice, current_user)
        except InventoryServiceError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    elif practice.materials:
        linked_loans = list_linked_loans_map([practice.id]).get(practice.id, [])

    practice = (
        db.query(PracticeRequest)
        .options(joinedload(PracticeRequest.laboratory), joinedload(PracticeRequest.materials))
        .filter(PracticeRequest.id == practice_id)
        .first()
    )
    sync_practice_requests_to_pocketbase()
    sync_practice_materials_to_pocketbase()
    publish_reservations_event(
        "practice_request.updated",
        "practice_request",
        {
            "practice_request_id": practice.id,
            "laboratory_id": practice.laboratory_id,
            "date": practice.date.isoformat(),
            "status": practice.status,
        },
    )
    return serialize_practice(practice, linked_loans)
