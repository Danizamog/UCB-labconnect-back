from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.application.container import tutorial_session_repo
from app.core.dependencies import ensure_any_permission, get_current_user
from app.notifications.store import notification_store
from app.realtime.manager import realtime_manager
from app.schemas.tutorial_session import TutorialSessionCreate, TutorialSessionResponse, TutorialSessionUpdate

router = APIRouter(prefix="/tutorial-sessions", tags=["tutorial-sessions"])


async def _broadcast_tutorial_notification(
    *,
    recipient_user_id: str,
    notification_type: str,
    title: str,
    message: str,
    payload: dict,
) -> None:
    notification = notification_store.create(
        recipient_user_id=recipient_user_id,
        notification_type=notification_type,
        title=title,
        message=message,
        payload=payload,
    )

    await realtime_manager.broadcast(
        {
            "topic": "user_notification",
            "action": "create",
            "recipients": [recipient_user_id],
            "record": notification.model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )


def _build_tutorial_update_notification(
    previous: TutorialSessionResponse,
    updated: TutorialSessionResponse,
    current_user: dict,
) -> tuple[str, str, dict] | None:
    changed_schedule = (
        previous.session_date != updated.session_date
        or previous.start_time != updated.start_time
        or previous.end_time != updated.end_time
    )
    changed_location = previous.location != updated.location or previous.laboratory_id != updated.laboratory_id
    changed_tutor = previous.tutor_name != updated.tutor_name or previous.tutor_email != updated.tutor_email

    if not changed_schedule and not changed_location and not changed_tutor:
        return None

    change_kinds: list[str] = []
    if changed_schedule:
        change_kinds.append("schedule")
    if changed_location:
        change_kinds.append("location")
    if changed_tutor:
        change_kinds.append("tutor")

    if change_kinds == ["schedule"]:
        title = "Cambio de Horario"
        message = "Tu tutoria cambio de horario. Revisa el nuevo bloque publicado."
    elif change_kinds == ["location"]:
        title = "Cambio de Laboratorio"
        message = "Tu tutoria cambio de laboratorio. Revisa la nueva ubicacion."
    elif change_kinds == ["tutor"]:
        title = "Cambio de Tutor"
        message = "Tu tutoria ahora sera atendida por otro tutor. Revisa el detalle actualizado."
    else:
        title = "Tutoria Actualizada"
        message = "La tutoria donde estas inscrito tuvo cambios importantes. Revisa el detalle actualizado."

    payload = {
        "tutorial_session_id": updated.id,
        "topic": updated.topic,
        "change_kinds": change_kinds,
        "old_tutor_name": previous.tutor_name,
        "new_tutor_name": updated.tutor_name,
        "old_tutor_email": previous.tutor_email,
        "new_tutor_email": updated.tutor_email,
        "old_session_date": previous.session_date,
        "new_session_date": updated.session_date,
        "old_start_time": previous.start_time,
        "new_start_time": updated.start_time,
        "old_end_time": previous.end_time,
        "new_end_time": updated.end_time,
        "old_location": previous.location,
        "new_location": updated.location,
        "old_laboratory_id": previous.laboratory_id,
        "new_laboratory_id": updated.laboratory_id,
        "actor_user_id": str(current_user.get("user_id") or ""),
        "actor_name": str(current_user.get("name") or current_user.get("username") or "Sistema"),
        "target_path": "/app/tutorias",
    }
    return title, message, payload


@router.get("", response_model=list[TutorialSessionResponse])
def list_public_tutorial_sessions(_: dict = Depends(get_current_user)) -> list[TutorialSessionResponse]:
    return tutorial_session_repo.list_public()


@router.get("/mine", response_model=list[TutorialSessionResponse])
def list_my_tutorial_sessions(current_user: dict = Depends(get_current_user)) -> list[TutorialSessionResponse]:
    ensure_any_permission(
        current_user,
        {"gestionar_tutorias"},
        "No tienes permisos para gestionar tutorias",
    )
    return tutorial_session_repo.list_for_tutor(current_user.get("user_id") or "")


@router.get("/my-enrollments", response_model=list[TutorialSessionResponse])
def list_my_enrolled_tutorial_sessions(current_user: dict = Depends(get_current_user)) -> list[TutorialSessionResponse]:
    return tutorial_session_repo.list_for_student(current_user.get("user_id") or "")


@router.get("/{session_id}", response_model=TutorialSessionResponse)
def get_tutorial_session(
    session_id: str,
    current_user: dict = Depends(get_current_user),
) -> TutorialSessionResponse:
    session = tutorial_session_repo.get_by_id(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tutoria no encontrada")

    is_admin = current_user.get("role") == "admin"
    can_manage = "gestionar_tutorias" in set(current_user.get("permissions") or [])
    is_owner = session.tutor_id == (current_user.get("user_id") or "")

    if not session.is_published and not (is_admin or can_manage or is_owner):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta tutoria")

    return session


@router.post("", response_model=TutorialSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_tutorial_session(
    body: TutorialSessionCreate,
    current_user: dict = Depends(get_current_user),
) -> TutorialSessionResponse:
    ensure_any_permission(
        current_user,
        {"gestionar_tutorias"},
        "No tienes permisos para publicar tutorias",
    )

    payload = body.model_copy(
        update={
            "tutor_id": body.tutor_id or current_user.get("user_id") or "",
            "tutor_name": body.tutor_name or current_user.get("name") or current_user.get("username") or "Tutor",
            "tutor_email": body.tutor_email or current_user.get("email") or "",
        }
    )

    try:
        created = tutorial_session_repo.create(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    await realtime_manager.broadcast(
        {
            "topic": "tutorial_session",
            "action": "create",
            "record": created.model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )
    return created


@router.post("/{session_id}/enroll", response_model=TutorialSessionResponse)
async def enroll_in_tutorial_session(
    session_id: str,
    current_user: dict = Depends(get_current_user),
) -> TutorialSessionResponse:
    try:
        updated = tutorial_session_repo.enroll(
            session_id,
            student_id=current_user.get("user_id") or "",
            student_name=current_user.get("name") or current_user.get("username") or "Estudiante",
            student_email=current_user.get("email") or "",
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    await realtime_manager.broadcast(
        {
            "topic": "tutorial_session",
            "action": "update",
            "record": updated.model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )
    return updated


@router.delete("/{session_id}/enroll", response_model=TutorialSessionResponse)
async def cancel_tutorial_enrollment(
    session_id: str,
    current_user: dict = Depends(get_current_user),
) -> TutorialSessionResponse:
    try:
        updated = tutorial_session_repo.unenroll(
            session_id,
            student_id=current_user.get("user_id") or "",
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    await realtime_manager.broadcast(
        {
            "topic": "tutorial_session",
            "action": "update",
            "record": updated.model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )
    return updated


@router.patch("/{session_id}", response_model=TutorialSessionResponse)
async def update_tutorial_session(
    session_id: str,
    body: TutorialSessionUpdate,
    current_user: dict = Depends(get_current_user),
) -> TutorialSessionResponse:
    ensure_any_permission(
        current_user,
        {"gestionar_tutorias"},
        "No tienes permisos para modificar tutorias",
    )

    existing = tutorial_session_repo.get_by_id(session_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tutoria no encontrada")

    is_admin = current_user.get("role") == "admin"
    if not is_admin and existing.tutor_id != (current_user.get("user_id") or ""):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes modificar una tutoria de otro tutor")

    normalized_body = body
    if not is_admin:
        normalized_body = body.model_copy(
            update={
                "tutor_id": existing.tutor_id,
                "tutor_name": body.tutor_name or existing.tutor_name,
                "tutor_email": body.tutor_email or existing.tutor_email,
            }
        )

    try:
        updated = tutorial_session_repo.update(session_id, normalized_body)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    notification_data = _build_tutorial_update_notification(existing, updated, current_user)
    if notification_data is not None:
        title, message, payload = notification_data
        actor_user_id = str(current_user.get("user_id") or "")
        for enrollment in updated.enrolled_students:
            if enrollment.student_id == actor_user_id:
                continue
            await _broadcast_tutorial_notification(
                recipient_user_id=enrollment.student_id,
                notification_type="tutorial_session_updated",
                title=title,
                message=message,
                payload=payload,
            )

    await realtime_manager.broadcast(
        {
            "topic": "tutorial_session",
            "action": "update",
            "record": updated.model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )
    return updated


@router.delete("/{session_id}", response_class=Response)
async def delete_tutorial_session(
    session_id: str,
    current_user: dict = Depends(get_current_user),
) -> None:
    ensure_any_permission(
        current_user,
        {"gestionar_tutorias"},
        "No tienes permisos para eliminar tutorias",
    )

    existing = tutorial_session_repo.get_by_id(session_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tutoria no encontrada")

    is_admin = current_user.get("role") == "admin"
    if not is_admin and existing.tutor_id != (current_user.get("user_id") or ""):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes eliminar una tutoria de otro tutor")

    deleted_result = tutorial_session_repo.delete(session_id)
    if deleted_result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tutoria no encontrada")

    deleted_session, enrollments = deleted_result
    for enrollment in enrollments:
        await _broadcast_tutorial_notification(
            recipient_user_id=enrollment.student_id,
            notification_type="tutorial_session_cancelled",
            title="Tutoria Cancelada",
            message=(
                f"La tutoria '{deleted_session.topic}' fue cancelada por el tutor. "
                "Tu inscripcion quedo anulada automaticamente."
            ),
            payload={
                "tutorial_session_id": deleted_session.id,
                "topic": deleted_session.topic,
                "tutor_name": deleted_session.tutor_name,
                "session_date": deleted_session.session_date,
                "start_time": deleted_session.start_time,
                "end_time": deleted_session.end_time,
                "location": deleted_session.location,
                "target_path": "/app/tutorias",
            },
        )

    await realtime_manager.broadcast(
        {
            "topic": "tutorial_session",
            "action": "delete",
            "record": {"id": session_id},
            "at": datetime.utcnow().isoformat(),
        }
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
