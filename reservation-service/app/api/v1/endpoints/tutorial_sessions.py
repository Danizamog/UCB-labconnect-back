from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status, Query

from app.application.container import tutorial_session_repo
from app.core.dependencies import ensure_any_permission, get_current_user
from app.notifications.store import notification_store
from app.realtime.manager import realtime_manager
from app.schemas.tutorial_session import TutorialSessionCreate, TutorialSessionResponse

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


@router.get("", response_model=list[TutorialSessionResponse])
def list_public_tutorial_sessions(
    q: str | None = Query(default=None, description="Buscar por tema (topic)"),
    laboratory_id: str | None = Query(default=None),
    session_date: str | None = Query(default=None, description="Fecha en formato YYYY-MM-DD"),
    is_published: bool | None = Query(default=None),
    sort: str | None = Query(default=None, description="Campo(s) para ordenar, coma-separados"),
    _: dict = Depends(get_current_user),
) -> list[TutorialSessionResponse]:
    return tutorial_session_repo.list_public_filtered(
        topic=q,
        laboratory_id=laboratory_id,
        session_date=session_date,
        is_published=is_published,
        sort=sort,
    )


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
            "tutor_email": body.tutor_email or "",
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


@router.patch("/{session_id}", response_model=TutorialSessionResponse)
async def update_tutorial_session(
    session_id: str,
    body: TutorialSessionCreate,
    current_user: dict = Depends(get_current_user),
) -> TutorialSessionResponse:
    ensure_any_permission(
        current_user,
        {"gestionar_tutorias"},
        "No tienes permisos para actualizar tutorias",
    )

    existing = tutorial_session_repo.get_by_id(session_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tutoria no encontrada")

    is_admin = current_user.get("role") == "admin"
    if not is_admin and existing.tutor_id != (current_user.get("user_id") or ""):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes editar una tutoria de otro tutor")

    payload = body.model_copy(
        update={
            "tutor_id": existing.tutor_id,
            "tutor_name": body.tutor_name or existing.tutor_name,
            "tutor_email": body.tutor_email or existing.tutor_email,
            "is_published": existing.is_published if body.is_published is None else body.is_published,
        }
    )

    try:
        updated = tutorial_session_repo.update(session_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    for enrollment in existing.enrolled_students:
        await _broadcast_tutorial_notification(
            recipient_user_id=enrollment.student_id,
            notification_type="tutorial_session_updated",
            title="Tutoria actualizada",
            message=(
                f"La tutoria '{updated.topic}' cambio de horario, laboratorio o cupos. "
                "Revisa el detalle actualizado antes de asistir."
            ),
            payload={
                "tutorial_session_id": updated.id,
                "topic": updated.topic,
                "old_location": existing.location,
                "new_location": updated.location,
                "old_session_date": existing.session_date,
                "new_session_date": updated.session_date,
                "old_start_time": existing.start_time,
                "old_end_time": existing.end_time,
                "new_start_time": updated.start_time,
                "new_end_time": updated.end_time,
                "target_path": "/app/tutorias",
            },
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
        updated = tutorial_session_repo.cancel_enrollment(
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
