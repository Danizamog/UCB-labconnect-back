from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.email.sender import send_penalty_email
from app.core.dependencies import ensure_any_permission, get_current_user
from app.penalties.store import penalty_store
from app.notifications.store import notification_store
from app.realtime.manager import realtime_manager
from app.schemas.penalty import PenaltyCreate, PenaltyLiftRequest, PenaltyLiftResponse, PenaltyResponse

router = APIRouter(prefix="/penalties", tags=["penalties"])
_MANAGE_PENALTIES = {"gestionar_penalizaciones"}


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
    normalized_email = str(body.user_email or "").strip().lower()
    if not normalized_user_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Debes indicar el usuario responsable")
    if not normalized_email:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Debes indicar el correo del usuario penalizado")
    if not str(body.reason or "").strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Debes registrar el motivo de la penalizacion")

    try:
        penalty = penalty_store.create(body, current_user=current_user, email_sent=False)
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
