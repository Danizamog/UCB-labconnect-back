from __future__ import annotations

from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.application.container import penalty_reactivation_history_store, user_penalty_repo
from app.core.config import settings
from app.email.sender import send_penalty_email, send_penalty_reactivation_email
from app.core.dependencies import ensure_any_permission, get_current_user
from app.notifications.store import notification_store
from app.realtime.manager import realtime_manager
from app.schemas.penalty import (
    PenaltyCreate,
    PenaltyLiftRequest,
    PenaltyLiftResponse,
    PenaltyReactivationContextResponse,
    PenaltyReactivationHistoryRecordCreate,
    PenaltyReactivationRequest,
    PenaltyReactivationResponse,
    PenaltyRegularizationStatus,
    PenaltyResponse,
)

router = APIRouter(prefix="/penalties", tags=["penalties"])
_MANAGE_PENALTIES = {"gestionar_penalizaciones"}
_REACTIVATE_ACCOUNT = {"gestionar_penalizaciones", "reactivar_cuentas"}


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


def _authorization_header(request: Request) -> str:
    header = str(request.headers.get("authorization") or "").strip()
    if not header:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Falta token Bearer")
    return header


async def _request_json(method: str, url: str, *, authorization: str, payload: dict | None = None) -> dict | list | None:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=4.0)) as client:
            response = await client.request(
                method,
                url,
                json=payload,
                headers={
                    "Authorization": authorization,
                    "Content-Type": "application/json",
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo consultar un servicio dependiente para la reactivacion",
        ) from exc

    if response.status_code >= 400:
        detail = "No se pudo completar la operacion solicitada"
        try:
            data = response.json()
            if isinstance(data, dict):
                detail = str(data.get("detail") or detail)
        except ValueError:
            pass
        raise HTTPException(status_code=response.status_code, detail=detail)

    if not response.content:
        return None
    return response.json()


async def _fetch_user_profile(user_id: str, authorization: str) -> dict:
    payload = await _request_json(
        "GET",
        f"{settings.auth_service_url.rstrip('/')}/v1/users/{user_id}",
        authorization=authorization,
    )
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Respuesta invalida al consultar el usuario")
    return payload


async def _set_user_active(user_id: str, authorization: str, *, is_active: bool) -> dict:
    payload = await _request_json(
        "PUT",
        f"{settings.auth_service_url.rstrip('/')}/v1/users/{user_id}",
        authorization=authorization,
        payload={"is_active": is_active},
    )
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Respuesta invalida al actualizar el usuario")
    return payload


async def _fetch_user_flag(user_email: str, authorization: str) -> dict | None:
    if not str(user_email or "").strip():
        return None

    payload = await _request_json(
        "GET",
        f"{settings.inventory_service_url.rstrip('/')}/v1/asset-maintenance/user-flags",
        authorization=authorization,
    )
    if not isinstance(payload, list):
        return None

    normalized_email = str(user_email or "").strip().lower()
    for item in payload:
        if not isinstance(item, dict):
            continue
        if str(item.get("borrower_email") or "").strip().lower() == normalized_email:
            return item
    return None


def _build_regularization_status(flag: dict | None) -> PenaltyRegularizationStatus:
    active_damage_count = int(flag.get("active_damage_count") or 0) if isinstance(flag, dict) else 0
    has_open_damage_flags = active_damage_count > 0
    if has_open_damage_flags and isinstance(flag, dict):
        summary = (
            f"El usuario mantiene {active_damage_count} incidente(s) pendiente(s) "
            f"relacionado(s) con {str(flag.get('latest_asset_name') or 'un activo').strip()}."
        )
    else:
        summary = "No existen banderas activas de dano. La situacion del usuario esta regularizada."

    return PenaltyRegularizationStatus(
        is_regularized=not has_open_damage_flags,
        has_open_damage_flags=has_open_damage_flags,
        active_damage_count=active_damage_count,
        summary=summary,
        latest_ticket_id=str(flag.get("latest_ticket_id") or "").strip() if isinstance(flag, dict) else "",
        latest_ticket_title=str(flag.get("latest_ticket_title") or "").strip() if isinstance(flag, dict) else "",
        latest_asset_name=str(flag.get("latest_asset_name") or "").strip() if isinstance(flag, dict) else "",
        latest_reported_at=str(flag.get("latest_reported_at") or "").strip() if isinstance(flag, dict) else "",
    )


def _resolve_block_status(*, user_is_active: bool, active_penalty_count: int) -> str:
    if active_penalty_count > 0:
        return "blocked"
    if user_is_active:
        return "active"
    return "inactive"


async def _build_reactivation_context(user_id: str, authorization: str) -> PenaltyReactivationContextResponse:
    user_profile = await _fetch_user_profile(user_id, authorization)
    penalties = user_penalty_repo.list_for_user(user_id)
    active_penalties = [item for item in penalties if item.is_active]
    primary_penalty = active_penalties[0] if active_penalties else None
    primary_penalty_email = primary_penalty.user_email if primary_penalty else ""
    primary_penalty_name = primary_penalty.user_name if primary_penalty else ""
    user_email = str(user_profile.get("username") or primary_penalty_email or "").strip()
    regularization = _build_regularization_status(await _fetch_user_flag(user_email, authorization))
    active_penalty_count = len(active_penalties)
    can_reactivate = active_penalty_count == 1 and regularization.is_regularized
    privileges_restored_if_confirmed = can_reactivate

    return PenaltyReactivationContextResponse(
        user_id=str(user_profile.get("id") or user_id).strip(),
        user_name=str(user_profile.get("name") or primary_penalty_name or "").strip(),
        user_email=user_email,
        user_is_active=bool(user_profile.get("is_active", True)),
        block_status=_resolve_block_status(
            user_is_active=bool(user_profile.get("is_active", True)),
            active_penalty_count=active_penalty_count,
        ),
        active_penalty=primary_penalty,
        active_penalty_count=active_penalty_count,
        can_reactivate=can_reactivate,
        privileges_restored_if_confirmed=privileges_restored_if_confirmed,
        regularization=regularization,
        history=penalty_reactivation_history_store.list_for_user(user_id),
    )


async def _execute_reactivation(
    penalty_id: str,
    *,
    request: Request,
    current_user: dict,
    lift_reason: str,
    resolution_notes: str,
    action_source: str,
) -> PenaltyReactivationResponse:
    authorization = _authorization_header(request)
    existing_penalty = user_penalty_repo.get_by_id(penalty_id)
    if existing_penalty is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Penalizacion no encontrada")
    if not existing_penalty.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La penalizacion ya no mantiene un bloqueo activo sobre el usuario",
        )

    user_profile = await _fetch_user_profile(existing_penalty.user_id, authorization)
    user_email = str(existing_penalty.user_email or user_profile.get("username") or "").strip().lower()
    regularization = _build_regularization_status(await _fetch_user_flag(user_email, authorization))
    if not regularization.is_regularized:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=regularization.summary,
        )

    other_active_penalties = [
        item
        for item in user_penalty_repo.list_for_user(existing_penalty.user_id)
        if item.is_active and item.id != existing_penalty.id
    ]
    if other_active_penalties:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El usuario aun tiene otras penalizaciones activas. Resuelvelas antes de reactivar la cuenta.",
        )

    user_was_inactive = not bool(user_profile.get("is_active", True))
    if user_was_inactive:
        await _set_user_active(existing_penalty.user_id, authorization, is_active=True)

    lifted = user_penalty_repo.lift(
        penalty_id,
        current_user=current_user,
        lift_reason=lift_reason,
    )
    if lifted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Penalizacion no encontrada")

    await _notify_penalty_lifted(lifted)
    await _broadcast_penalty_event("lift", lifted)

    email_sent = send_penalty_reactivation_email(
        penalty=lifted,
        actor_name=str(current_user.get("name") or "").strip(),
    )
    active_penalty_count_after = len([item for item in user_penalty_repo.list_for_user(lifted.user_id) if item.is_active])
    privileges_restored = active_penalty_count_after == 0

    history_record = penalty_reactivation_history_store.create(
        PenaltyReactivationHistoryRecordCreate(
            penalty_id=lifted.id,
            user_id=lifted.user_id,
            user_name=lifted.user_name,
            user_email=user_email,
            actor_user_id=str(current_user.get("user_id") or "").strip(),
            actor_name=str(current_user.get("name") or current_user.get("username") or "Administrador").strip(),
            executed_at=datetime.now(UTC).isoformat(),
            lift_reason=lift_reason,
            resolution_notes=resolution_notes,
            action_source=action_source or "admin_profile",
            user_was_inactive=user_was_inactive,
            user_is_active_after=True,
            privileges_restored=privileges_restored,
            active_penalty_count_after=active_penalty_count_after,
            active_damage_count_at_validation=regularization.active_damage_count,
            regularization_confirmed=regularization.is_regularized,
            regularization_summary=regularization.summary,
            notification_sent=True,
            email_sent=email_sent,
        )
    )

    return PenaltyReactivationResponse(
        penalty=lifted,
        reactivation=history_record,
        regularization=regularization,
        privileges_restored=privileges_restored,
        active_block_removed=not lifted.is_active,
        user_status=_resolve_block_status(user_is_active=True, active_penalty_count=active_penalty_count_after),
    )


@router.get("", response_model=list[PenaltyResponse])
def list_penalties(
    active_only: bool = Query(default=False),
    current_user: dict = Depends(get_current_user),
) -> list[PenaltyResponse]:
    items = user_penalty_repo.list_all()
    if active_only:
        items = [item for item in items if item.is_active]
    return items


@router.get("/mine", response_model=list[PenaltyResponse])
def list_my_penalties(current_user: dict = Depends(get_current_user)) -> list[PenaltyResponse]:
    user_id = str(current_user.get("user_id") or "").strip()
    if not user_id:
        return []
    return user_penalty_repo.list_for_user(user_id)


@router.get("/reactivation-context/{user_id}", response_model=PenaltyReactivationContextResponse)
async def get_reactivation_context(
    user_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> PenaltyReactivationContextResponse:
    ensure_any_permission(current_user, _REACTIVATE_ACCOUNT, "No tienes permisos para reactivar cuentas")
    return await _build_reactivation_context(user_id, _authorization_header(request))


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
        penalty = user_penalty_repo.create(body, current_user=current_user, email_sent=False)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    email_sent = send_penalty_email(penalty=penalty)
    if email_sent:
        penalty = user_penalty_repo.update_email_delivery(penalty.id, email_sent=True) or penalty

    await _notify_penalty_applied(penalty)
    await _broadcast_penalty_event("create", penalty)
    return penalty


@router.post("/{penalty_id}/reactivate", response_model=PenaltyReactivationResponse)
async def reactivate_user_account(
    penalty_id: str,
    body: PenaltyReactivationRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> PenaltyReactivationResponse:
    ensure_any_permission(current_user, _REACTIVATE_ACCOUNT, "No tienes permisos para reactivar cuentas")
    return await _execute_reactivation(
        penalty_id,
        request=request,
        current_user=current_user,
        lift_reason=str(body.lift_reason or "").strip(),
        resolution_notes=str(body.resolution_notes or "").strip(),
        action_source=str(body.action_source or "admin_profile").strip() or "admin_profile",
    )


@router.patch("/{penalty_id}/lift", response_model=PenaltyLiftResponse)
async def lift_penalty(
    penalty_id: str,
    body: PenaltyLiftRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> PenaltyLiftResponse:
    ensure_any_permission(current_user, _MANAGE_PENALTIES, "No tienes permisos para gestionar penalizaciones")
    result = await _execute_reactivation(
        penalty_id,
        request=request,
        current_user=current_user,
        lift_reason=str(body.lift_reason or "").strip(),
        resolution_notes="",
        action_source="penalties_panel",
    )
    return PenaltyLiftResponse(penalty=result.penalty, privileges_restored=result.privileges_restored)
