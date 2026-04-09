from __future__ import annotations

from datetime import UTC, datetime
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.application.container import pb_client
from app.email.sender import send_penalty_email
from app.core.config import settings
from app.core.datetime_utils import now_local_naive, parse_datetime
from app.core.dependencies import ensure_any_permission, get_current_user
from app.penalties.store import penalty_store
from app.notifications.store import notification_store
from app.realtime.manager import realtime_manager
from app.schemas.penalty import PenaltyCreate, PenaltyLiftRequest, PenaltyLiftResponse, PenaltyResponse

router = APIRouter(prefix="/penalties", tags=["penalties"])
_MANAGE_PENALTIES = {"gestionar_penalizaciones"}
_INSTITUTIONAL_EMAIL_RE = re.compile(r"^[^@\s]+@ucb\.edu\.bo$", re.IGNORECASE)
_TICKET_TYPE_BY_EVIDENCE = {
    "damage_report": "damage",
    "maintenance_report": "maintenance",
}


def _notify_payload(penalty: PenaltyResponse) -> dict:
    return {
        "penalty_id": penalty.id,
        "reason": penalty.reason,
        "starts_at": penalty.starts_at,
        "ends_at": penalty.ends_at,
        "evidence_type": penalty.evidence_type,
        "evidence_report_id": penalty.evidence_report_id,
        "asset_id": penalty.asset_id,
        "status": penalty.status,
        "target_path": "/app/reservas/nueva",
    }


async def _broadcast_penalty_event(action: str, penalty: PenaltyResponse) -> None:
    await realtime_manager.broadcast(
        {
            "topic": "user_penalty",
            "action": action,
            "recipients": [penalty.user_id],
            "record": penalty.model_dump(),
            "at": datetime.now(UTC).isoformat(),
        }
    )


async def _notify_penalty_applied(penalty: PenaltyResponse) -> None:
    notification = notification_store.create(
        recipient_user_id=penalty.user_id,
        notification_type="penalty_applied",
        title="Cuenta suspendida temporalmente",
        message="Se registro una penalizacion activa sobre tu cuenta por un dano reportado.",
        payload=_notify_payload(penalty),
    )
    await realtime_manager.broadcast(
        {
            "topic": "user_notification",
            "action": "create",
            "recipients": [penalty.user_id],
            "record": notification.model_dump(),
            "at": datetime.now(UTC).isoformat(),
        }
    )


async def _notify_penalty_lifted(penalty: PenaltyResponse) -> None:
    notification = notification_store.create(
        recipient_user_id=penalty.user_id,
        notification_type="penalty_lifted",
        title="Penalizacion levantada",
        message="Tu cuenta recupero el acceso para solicitar nuevas reservas.",
        payload=_notify_payload(penalty),
    )
    await realtime_manager.broadcast(
        {
            "topic": "user_notification",
            "action": "create",
            "recipients": [penalty.user_id],
            "record": notification.model_dump(),
            "at": datetime.now(UTC).isoformat(),
        }
    )


def _get_record_from_collection(collection: str, record_id: str) -> dict | None:
    normalized_id = str(record_id or "").strip()
    if not normalized_id:
        return None

    local_record = pb_client.fallback_request("GET", f"/api/collections/{collection}/records/{normalized_id}")
    if isinstance(local_record, dict):
        return local_record

    try:
        remote_record = pb_client.request("GET", f"/api/collections/{collection}/records/{normalized_id}")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None
        raise

    return remote_record if isinstance(remote_record, dict) else None


def _list_collection_records(collection: str, *, sort: str = "-reported_at") -> list[dict]:
    merged: dict[str, dict] = {}

    local_payload = pb_client.fallback_request(
        "GET",
        f"/api/collections/{collection}/records",
        params={"page": 1, "perPage": 500, "sort": sort},
    )
    if isinstance(local_payload, dict):
        for item in local_payload.get("items", []):
            if isinstance(item, dict):
                record_id = str(item.get("id") or "").strip()
                if record_id:
                    merged[record_id] = item

    try:
        remote_payload = pb_client.request(
            "GET",
            f"/api/collections/{collection}/records",
            params={"page": 1, "perPage": 500, "sort": sort},
        )
    except httpx.HTTPStatusError:
        remote_payload = None

    if isinstance(remote_payload, dict):
        for item in remote_payload.get("items", []):
            if isinstance(item, dict):
                record_id = str(item.get("id") or "").strip()
                if record_id and record_id not in merged:
                    merged[record_id] = item

    return list(merged.values())


def _resolve_user_record(user_id: str) -> dict | None:
    return _get_record_from_collection(settings.pb_users_collection, user_id)


def _find_inventory_record(path: str, *, record_id: str) -> dict | None:
    normalized_id = str(record_id or "").strip()
    if not normalized_id:
        return None

    try:
        response = httpx.get(
            f"{settings.inventory_service_url}{path}",
            timeout=max(settings.pocketbase_timeout_seconds, 5),
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return None

    try:
        payload = response.json()
    except ValueError:
        return None

    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and str(item.get("id") or "").strip() == normalized_id:
                return item
        return None

    if isinstance(payload, dict) and str(payload.get("id") or "").strip() == normalized_id:
        return payload

    return None


def _resolve_asset_record(asset_id: str) -> dict | None:
    record = _get_record_from_collection(settings.pb_inventory_assets_collection, asset_id)
    if record is not None:
        return record
    return _find_inventory_record("/v1/assets", record_id=asset_id)


def _resolve_laboratory_record(laboratory_id: str) -> dict | None:
    record = _get_record_from_collection(settings.pb_laboratory_collection, laboratory_id)
    if record is not None:
        return record
    return _find_inventory_record("/v1/laboratories", record_id=laboratory_id)


def _resolve_evidence_record(*, evidence_type: str, evidence_ticket_id: str, evidence_report_id: str) -> dict | None:
    collection = settings.pb_inventory_asset_maintenance_tickets_collection
    expected_ticket_type = _TICKET_TYPE_BY_EVIDENCE.get(str(evidence_type or "").strip(), "")

    if evidence_ticket_id:
        record = _get_record_from_collection(collection, evidence_ticket_id)
        if record and str(record.get("ticket_type") or "").strip() == expected_ticket_type:
            return record

    normalized_report_id = str(evidence_report_id or "").strip()
    if not normalized_report_id:
        return None

    for record in _list_collection_records(collection):
        candidate_type = str(record.get("ticket_type") or "").strip()
        candidate_report_id = str(record.get("evidence_report_id") or record.get("id") or "").strip()
        candidate_id = str(record.get("id") or "").strip()
        if candidate_type != expected_ticket_type:
            continue
        if normalized_report_id in {candidate_report_id, candidate_id}:
            return record
    return None


@router.get("", response_model=list[PenaltyResponse])
def list_penalties(
    active_only: bool = Query(default=False),
    current_user: dict = Depends(get_current_user),
) -> list[PenaltyResponse]:
    ensure_any_permission(current_user, _MANAGE_PENALTIES, "No tienes permisos para gestionar penalizaciones")
    items = penalty_store.list_all()
    if active_only:
        items = [item for item in items if item.is_active]
    return items


@router.get("/mine", response_model=list[PenaltyResponse])
def list_my_penalties(current_user: dict = Depends(get_current_user)) -> list[PenaltyResponse]:
    user_id = str(current_user.get("user_id") or "").strip()
    if not user_id:
        return []
    return penalty_store.list_for_user(user_id)


@router.post("", response_model=PenaltyResponse, status_code=status.HTTP_201_CREATED)
async def create_penalty(
    body: PenaltyCreate,
    current_user: dict = Depends(get_current_user),
) -> PenaltyResponse:
    ensure_any_permission(current_user, _MANAGE_PENALTIES, "No tienes permisos para gestionar penalizaciones")

    normalized_user_id = str(body.user_id or "").strip()
    normalized_reason = str(body.reason or "").strip()
    normalized_report_id = str(body.evidence_report_id or "").strip()
    normalized_ticket_id = str(body.evidence_ticket_id or "").strip()
    normalized_incident_lab = str(body.incident_laboratory_id or "").strip()
    normalized_incident_scope = str(body.incident_scope or "asset").strip().lower()
    normalized_asset_id = str(body.asset_id or "").strip()

    if not normalized_user_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Debes indicar el usuario responsable")
    if len(normalized_reason) < 10:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Debes registrar el motivo de la penalizacion")
    if len(str(body.notes or "")) > 500:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Las notas internas no deben superar 500 caracteres")
    if normalized_incident_scope not in {"asset", "laboratory"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El alcance del incidente no es valido")
    if not normalized_incident_lab:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Debes indicar el laboratorio del incidente")
    if not str(body.incident_date or "").strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Debes indicar la fecha del incidente")
    if not str(body.incident_start_time or "").strip() or not str(body.incident_end_time or "").strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Debes indicar el bloque horario del incidente")
    if str(body.incident_end_time or "").strip() <= str(body.incident_start_time or "").strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El bloque del incidente debe terminar despues de la hora de inicio")
    if normalized_incident_scope == "asset" and not normalized_asset_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Debes seleccionar el equipo afectado")
    if not normalized_report_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Debes enlazar un reporte tecnico como evidencia")

    if _resolve_laboratory_record(normalized_incident_lab) is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El laboratorio del incidente no existe")

    user_record = _resolve_user_record(normalized_user_id)
    if user_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El usuario responsable no existe en el sistema")
    if not bool(user_record.get("is_active", True)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No puedes penalizar una cuenta inactiva")

    normalized_email = str(user_record.get("email") or user_record.get("username") or "").strip().lower()
    normalized_user_name = str(user_record.get("name") or user_record.get("username") or normalized_user_id).strip()
    if not normalized_email:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El usuario no tiene un correo institucional registrado")
    if not _INSTITUTIONAL_EMAIL_RE.match(normalized_email):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El correo del usuario debe ser institucional @ucb.edu.bo")

    try:
        starts_at = parse_datetime(body.starts_at) if body.starts_at else now_local_naive()
        ends_at = parse_datetime(body.ends_at)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if ends_at <= starts_at:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="La fecha de fin de la penalizacion debe ser posterior al inicio")
    if ends_at <= now_local_naive():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="La penalizacion debe terminar en una fecha futura")

    blocking_penalty = penalty_store.get_blocking_for_user(normalized_user_id)
    if blocking_penalty is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El usuario ya tiene una penalizacion activa o programada. "
                f"Vigente hasta {blocking_penalty.ends_at}"
            ),
        )

    evidence_record = _resolve_evidence_record(
        evidence_type=body.evidence_type,
        evidence_ticket_id=normalized_ticket_id,
        evidence_report_id=normalized_report_id,
    )
    if evidence_record is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El reporte tecnico seleccionado no existe o no coincide con el tipo de evidencia")
    if normalized_asset_id and str(evidence_record.get("asset_id") or "").strip() and str(evidence_record.get("asset_id") or "").strip() != normalized_asset_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="La evidencia seleccionada no corresponde al equipo afectado")

    resolved_asset_id = normalized_asset_id or str(evidence_record.get("asset_id") or "").strip()
    if resolved_asset_id:
        asset_record = _resolve_asset_record(resolved_asset_id)
        if asset_record is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El equipo asociado a la penalizacion ya no existe en inventario")
        if str(asset_record.get("laboratory_id") or "").strip() != normalized_incident_lab:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El equipo o la evidencia seleccionados no pertenecen al laboratorio del incidente")

    normalized_body = body.model_copy(
        update={
            "user_name": normalized_user_name,
            "user_email": normalized_email,
            "asset_id": resolved_asset_id,
            "evidence_ticket_id": str(evidence_record.get("id") or normalized_ticket_id or "").strip(),
            "evidence_report_id": str(evidence_record.get("evidence_report_id") or normalized_report_id).strip(),
            "incident_scope": normalized_incident_scope,
            "incident_laboratory_id": normalized_incident_lab,
        }
    )

    try:
        penalty = penalty_store.create(normalized_body, current_user=current_user, email_sent=False)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    email_sent = send_penalty_email(penalty=penalty)
    if email_sent:
        penalty = penalty_store.update_email_delivery(penalty.id, email_sent=True) or penalty

    await _notify_penalty_applied(penalty)
    await _broadcast_penalty_event("create", penalty)
    return penalty


@router.patch("/{penalty_id}/lift", response_model=PenaltyLiftResponse)
async def lift_penalty(
    penalty_id: str,
    body: PenaltyLiftRequest,
    current_user: dict = Depends(get_current_user),
) -> PenaltyLiftResponse:
    ensure_any_permission(current_user, _MANAGE_PENALTIES, "No tienes permisos para gestionar penalizaciones")
    lifted = penalty_store.lift(
        penalty_id,
        current_user=current_user,
        lift_reason=str(body.lift_reason or "").strip(),
    )
    if lifted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Penalizacion no encontrada")

    await _notify_penalty_lifted(lifted)
    await _broadcast_penalty_event("lift", lifted)
    return PenaltyLiftResponse(penalty=lifted, privileges_restored=True)
