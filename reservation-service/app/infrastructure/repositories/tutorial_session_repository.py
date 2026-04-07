from __future__ import annotations

from calendar import monthrange
from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4

from app.core.datetime_utils import combine_date_time, now_local_naive, parse_datetime
from app.infrastructure.repositories.lab_reservation_repository import LabReservationRepository
from app.schemas.tutorial_session import (
    TutorialEnrollmentResponse,
    TutorialSessionCreate,
    TutorialSessionResponse,
)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _format_iso_utc(value: datetime) -> str:
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def _has_overlap(start_a: str, end_a: str, start_b: str, end_b: str) -> bool:
    a_start = parse_datetime(start_a)
    a_end = parse_datetime(end_a)
    b_start = parse_datetime(start_b)
    b_end = parse_datetime(end_b)
    return a_start < b_end and b_start < a_end


def _max_allowed_session_date(base_day):
    next_month = base_day.month + 1
    year = base_day.year
    if next_month > 12:
        next_month = 1
        year += 1

    day = min(base_day.day, monthrange(year, next_month)[1])
    return base_day.replace(year=year, month=next_month, day=day)


class TutorialSessionRepository:
    def __init__(self, reservation_repo: LabReservationRepository) -> None:
        self._reservation_repo = reservation_repo
        self._sessions: dict[str, TutorialSessionResponse] = {}
        self._lock = Lock()

    def _build_session(self, session_id: str, body: TutorialSessionCreate) -> TutorialSessionResponse:
        topic = str(body.topic or "").strip()
        description = str(body.description or "").strip()
        location = str(body.location or "").strip()
        max_students = int(body.max_students or 0)

        if len(topic) < 5:
            raise ValueError("Debes ingresar un tema claro de al menos 5 caracteres")

        if not location:
            raise ValueError("Debes seleccionar el laboratorio donde se realizara la tutoria")

        if max_students <= 0 or max_students > 50:
            raise ValueError("La capacidad maxima debe estar entre 1 y 50 estudiantes")

        start_dt = combine_date_time(datetime.fromisoformat(body.session_date).date(), body.start_time)
        end_dt = combine_date_time(datetime.fromisoformat(body.session_date).date(), body.end_time)
        if end_dt <= start_dt:
            raise ValueError("La hora de fin debe ser posterior a la hora de inicio")

        if start_dt.minute != 0 or end_dt.minute != 0:
            raise ValueError("Las tutorias deben publicarse usando bloques horarios exactos")

        if (end_dt - start_dt).total_seconds() % 3600 != 0:
            raise ValueError("La duracion de la tutoria debe respetar bloques completos de una hora")

        now = now_local_naive()
        if start_dt <= now:
            raise ValueError("No puedes publicar tutorias en horarios pasados o que ya comenzaron")

        max_allowed_day = _max_allowed_session_date(now.date())
        if start_dt.date() > max_allowed_day:
            raise ValueError("Solo puedes publicar tutorias con un maximo de un mes de anticipacion")

        if len(description) > 400:
            raise ValueError("La descripcion no puede superar los 400 caracteres")

        created_at = _iso_now()
        return TutorialSessionResponse(
            id=session_id,
            tutor_id=str(body.tutor_id or "").strip(),
            tutor_name=str(body.tutor_name or "").strip() or "Tutor",
            tutor_email=str(body.tutor_email or "").strip(),
            topic=topic,
            description=description,
            laboratory_id=str(body.laboratory_id or "").strip(),
            location=location,
            session_date=str(body.session_date),
            start_time=str(body.start_time),
            end_time=str(body.end_time),
            start_at=_format_iso_utc(start_dt),
            end_at=_format_iso_utc(end_dt),
            max_students=max_students,
            is_published=True if body.is_published is None else bool(body.is_published),
            enrolled_students=[],
            created=created_at,
            updated=created_at,
        )

    def _validate_no_conflicts(self, candidate: TutorialSessionResponse, skip_id: str | None = None) -> None:
        tutor_id = str(candidate.tutor_id or "").strip()
        if not tutor_id:
            raise ValueError("No se pudo identificar al tutor que publica la sesion")

        for session in self.list_all(include_past=True):
            if skip_id and session.id == skip_id:
                continue
            if session.laboratory_id == candidate.laboratory_id and _has_overlap(
                candidate.start_at,
                candidate.end_at,
                session.start_at,
                session.end_at,
            ):
                raise ValueError("Ya existe otra tutoria publicada en ese laboratorio y horario")
            if session.tutor_id != tutor_id:
                continue
            if _has_overlap(candidate.start_at, candidate.end_at, session.start_at, session.end_at):
                raise ValueError("Ya tienes otra tutoria publicada que se cruza con ese horario")

        for reservation in self._reservation_repo.list_all():
            if reservation.requested_by != tutor_id:
                continue
            if reservation.status in {"rejected", "cancelled"}:
                continue
            if _has_overlap(candidate.start_at, candidate.end_at, reservation.start_at, reservation.end_at):
                raise ValueError(
                    "Este horario se cruza con una reserva de laboratorio propia. Ajusta la tutoria antes de publicarla",
                )

    def list_all(self, *, include_past: bool = False) -> list[TutorialSessionResponse]:
        with self._lock:
            sessions = list(self._sessions.values())

        now = now_local_naive()
        filtered = []
        for session in sessions:
            if not include_past and parse_datetime(session.end_at) < now:
                continue
            filtered.append(session)
        return sorted(filtered, key=lambda item: (item.session_date, item.start_time, item.topic))

    def list_public(self) -> list[TutorialSessionResponse]:
        return [session for session in self.list_all() if session.is_published]

    def list_for_tutor(self, tutor_id: str) -> list[TutorialSessionResponse]:
        normalized_tutor_id = str(tutor_id or "").strip()
        return [session for session in self.list_all(include_past=True) if session.tutor_id == normalized_tutor_id]

    def get_by_id(self, session_id: str) -> TutorialSessionResponse | None:
        with self._lock:
            return self._sessions.get(session_id)

    def create(self, body: TutorialSessionCreate) -> TutorialSessionResponse:
        session = self._build_session(str(uuid4()), body)
        self._validate_no_conflicts(session)

        with self._lock:
            self._sessions[session.id] = session

        return session

    def enroll(
        self,
        session_id: str,
        *,
        student_id: str,
        student_name: str,
        student_email: str = "",
    ) -> TutorialSessionResponse:
        normalized_student_id = str(student_id or "").strip()
        if not normalized_student_id:
            raise ValueError("No se pudo identificar al estudiante")

        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError("Tutoria no encontrada")
            if not session.is_published:
                raise ValueError("La tutoria ya no esta disponible")
            if normalized_student_id == session.tutor_id:
                raise ValueError("El tutor no puede inscribirse en su propia tutoria")
            if any(enrollment.student_id == normalized_student_id for enrollment in session.enrolled_students):
                raise ValueError("Ya estas inscrito en esta tutoria")
            if session.seats_left <= 0:
                raise ValueError("La tutoria ya no tiene cupos disponibles")
            if parse_datetime(session.start_at) <= now_local_naive():
                raise ValueError("La tutoria ya comenzo o finalizo")

            next_enrollments = [
                *session.enrolled_students,
                TutorialEnrollmentResponse(
                    student_id=normalized_student_id,
                    student_name=str(student_name or "").strip() or "Estudiante",
                    student_email=str(student_email or "").strip(),
                    created_at=_iso_now(),
                ),
            ]
            updated = session.model_copy(update={"enrolled_students": next_enrollments, "updated": _iso_now()})
            self._sessions[session_id] = updated
            return updated

    def delete(self, session_id: str) -> tuple[TutorialSessionResponse, list[TutorialEnrollmentResponse]] | None:
        with self._lock:
            session = self._sessions.pop(session_id, None)

        if session is None:
            return None

        return session, list(session.enrolled_students)
