from __future__ import annotations

from calendar import monthrange
from datetime import UTC, datetime

from app.core.config import settings
from app.core.datetime_utils import combine_date_time, now_local_naive, parse_datetime
from app.infrastructure.pocketbase_base import PocketBaseClient
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


def _escape_filter_value(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


class TutorialSessionRepository:
    def __init__(self, client: PocketBaseClient, reservation_repo: LabReservationRepository) -> None:
        self._client = client
        self._reservation_repo = reservation_repo
        self._sessions_base = f"/api/collections/{settings.pb_tutorial_session_collection}/records"
        self._enrollments_base = f"/api/collections/{settings.pb_tutorial_enrollment_collection}/records"

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

    def _map_enrollment(self, record: dict) -> TutorialEnrollmentResponse:
        return TutorialEnrollmentResponse(
            student_id=str(record.get("student_id") or ""),
            student_name=str(record.get("student_name") or "Estudiante"),
            student_email=str(record.get("student_email") or ""),
            created_at=str(record.get("created_at") or record.get("created") or ""),
        )

    def _map_session(self, record: dict, enrollments: list[TutorialEnrollmentResponse]) -> TutorialSessionResponse:
        return TutorialSessionResponse(
            id=str(record.get("id") or ""),
            tutor_id=str(record.get("tutor_id") or ""),
            tutor_name=str(record.get("tutor_name") or "Tutor"),
            tutor_email=str(record.get("tutor_email") or ""),
            topic=str(record.get("topic") or ""),
            description=str(record.get("description") or ""),
            laboratory_id=str(record.get("laboratory_id") or ""),
            location=str(record.get("location") or ""),
            session_date=str(record.get("session_date") or ""),
            start_time=str(record.get("start_time") or ""),
            end_time=str(record.get("end_time") or ""),
            start_at=str(record.get("start_at") or ""),
            end_at=str(record.get("end_at") or ""),
            max_students=int(record.get("max_students") or 0),
            is_published=bool(record.get("is_published", True)),
            enrolled_students=enrollments,
            created=str(record.get("created") or ""),
            updated=str(record.get("updated") or ""),
        )

    def _list_records(self, base_path: str, *, filter_expression: str | None = None, sort: str | None = "created") -> list[dict]:
        items: list[dict] = []
        page = 1

        while True:
            params = {
                "page": page,
                "perPage": 200,
                **({"filter": filter_expression} if filter_expression else {}),
            }
            if sort:
                params["sort"] = sort

            data = self._client.request(
                "GET",
                base_path,
                params=params,
            )

            if not isinstance(data, dict):
                break

            batch = data.get("items", [])
            if not isinstance(batch, list) or not batch:
                break

            items.extend(item for item in batch if isinstance(item, dict))
            total_pages = int(data.get("totalPages", page))
            if page >= total_pages:
                break
            page += 1

        return items

    def _list_session_records(self) -> list[dict]:
        return self._list_records(self._sessions_base, sort="session_date,start_time")

    def _list_enrollment_records(self, *, session_id: str | None = None, student_id: str | None = None) -> list[dict]:
        clauses: list[str] = []
        if session_id:
            clauses.append(f'session_id="{_escape_filter_value(session_id)}"')
        if student_id:
            clauses.append(f'student_id="{_escape_filter_value(student_id)}"')
        filter_expression = " && ".join(clauses) if clauses else None
        return self._list_records(self._enrollments_base, filter_expression=filter_expression, sort=None)

    def _build_enrollment_map(self, session_records: list[dict]) -> dict[str, list[TutorialEnrollmentResponse]]:
        session_ids = [str(record.get("id") or "").strip() for record in session_records if str(record.get("id") or "").strip()]
        if not session_ids:
            return {}

        enrollments = self._list_enrollment_records()
        grouped: dict[str, list[TutorialEnrollmentResponse]] = {session_id: [] for session_id in session_ids}
        known_ids = set(session_ids)
        for record in enrollments:
            session_id = str(record.get("session_id") or "").strip()
            if session_id not in known_ids:
                continue
            grouped.setdefault(session_id, []).append(self._map_enrollment(record))
        return grouped

    def _get_session_record(self, session_id: str) -> dict | None:
        try:
            data = self._client.request("GET", f"{self._sessions_base}/{session_id}")
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _get_session_or_raise(self, session_id: str) -> TutorialSessionResponse:
        session = self.get_by_id(session_id)
        if session is None:
            raise KeyError("Tutoria no encontrada")
        return session

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
        session_records = self._list_session_records()
        enrollment_map = self._build_enrollment_map(session_records)
        now = now_local_naive()

        sessions: list[TutorialSessionResponse] = []
        for record in session_records:
            session = self._map_session(record, enrollment_map.get(str(record.get("id") or ""), []))
            if not include_past and parse_datetime(session.end_at) < now:
                continue
            sessions.append(session)

        return sorted(sessions, key=lambda item: (item.session_date, item.start_time, item.topic))

    def list_public(self) -> list[TutorialSessionResponse]:
        return [session for session in self.list_all() if session.is_published]

    def list_for_tutor(self, tutor_id: str) -> list[TutorialSessionResponse]:
        normalized_tutor_id = str(tutor_id or "").strip()
        return [session for session in self.list_all(include_past=True) if session.tutor_id == normalized_tutor_id]

    def list_for_student(self, student_id: str) -> list[TutorialSessionResponse]:
        normalized_student_id = str(student_id or "").strip()
        if not normalized_student_id:
            return []

        enrolled_session_ids = {
            str(record.get("session_id") or "").strip()
            for record in self._list_enrollment_records(student_id=normalized_student_id)
            if str(record.get("session_id") or "").strip()
        }
        if not enrolled_session_ids:
            return []

        return [
            session for session in self.list_all(include_past=True)
            if session.id in enrolled_session_ids
        ]

    def get_by_id(self, session_id: str) -> TutorialSessionResponse | None:
        record = self._get_session_record(session_id)
        if record is None:
            return None
        enrollments = [self._map_enrollment(item) for item in self._list_enrollment_records(session_id=session_id)]
        return self._map_session(record, enrollments)

    def create(self, body: TutorialSessionCreate) -> TutorialSessionResponse:
        candidate = self._build_session("new", body)
        self._validate_no_conflicts(candidate)

        data = self._client.request(
            "POST",
            self._sessions_base,
            payload={
                "tutor_id": candidate.tutor_id,
                "tutor_name": candidate.tutor_name,
                "tutor_email": candidate.tutor_email,
                "topic": candidate.topic,
                "description": candidate.description,
                "laboratory_id": candidate.laboratory_id,
                "location": candidate.location,
                "session_date": candidate.session_date,
                "start_time": candidate.start_time,
                "end_time": candidate.end_time,
                "start_at": candidate.start_at,
                "end_at": candidate.end_at,
                "max_students": candidate.max_students,
                "is_published": candidate.is_published,
            },
        )
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al crear la tutoria")
        return self._map_session(data, [])

    def update(self, session_id: str, body: TutorialSessionCreate) -> TutorialSessionResponse:
        existing = self._get_session_or_raise(session_id)
        enrollments = list(existing.enrolled_students)

        merged_body = TutorialSessionCreate(
            topic=body.topic,
            description=body.description,
            laboratory_id=body.laboratory_id,
            location=body.location,
            session_date=body.session_date,
            start_time=body.start_time,
            end_time=body.end_time,
            max_students=body.max_students,
            tutor_id=body.tutor_id or existing.tutor_id,
            tutor_name=body.tutor_name or existing.tutor_name,
            tutor_email=body.tutor_email or existing.tutor_email,
            is_published=existing.is_published if body.is_published is None else body.is_published,
        )

        candidate = self._build_session(session_id, merged_body)
        if len(enrollments) > candidate.max_students:
            raise ValueError("No puedes reducir el cupo por debajo de los estudiantes ya inscritos")

        self._validate_no_conflicts(candidate, skip_id=session_id)
        data = self._client.request(
            "PATCH",
            f"{self._sessions_base}/{session_id}",
            payload={
                "tutor_id": candidate.tutor_id,
                "tutor_name": candidate.tutor_name,
                "tutor_email": candidate.tutor_email,
                "topic": candidate.topic,
                "description": candidate.description,
                "laboratory_id": candidate.laboratory_id,
                "location": candidate.location,
                "session_date": candidate.session_date,
                "start_time": candidate.start_time,
                "end_time": candidate.end_time,
                "start_at": candidate.start_at,
                "end_at": candidate.end_at,
                "max_students": candidate.max_students,
                "is_published": candidate.is_published,
            },
        )
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al actualizar la tutoria")
        return self._map_session(data, enrollments)

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

        session = self._get_session_or_raise(session_id)
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

        data = self._client.request(
            "POST",
            self._enrollments_base,
            payload={
                "session_id": session_id,
                "student_id": normalized_student_id,
                "student_name": str(student_name or "").strip() or "Estudiante",
                "student_email": str(student_email or "").strip(),
                "created_at": _iso_now(),
            },
        )
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al registrar la inscripcion")
        return self._get_session_or_raise(session_id)

    def cancel_enrollment(self, session_id: str, *, student_id: str) -> TutorialSessionResponse:
        normalized_student_id = str(student_id or "").strip()
        if not normalized_student_id:
            raise ValueError("No se pudo identificar al estudiante")

        session = self._get_session_or_raise(session_id)
        if parse_datetime(session.start_at) <= now_local_naive():
            raise ValueError("La tutoria ya comenzo o finalizo")

        enrollment_records = self._list_enrollment_records(session_id=session_id, student_id=normalized_student_id)
        if not enrollment_records:
            raise ValueError("No se encontro una inscripcion activa para esta tutoria")

        enrollment_id = str(enrollment_records[0].get("id") or "").strip()
        if not enrollment_id:
            raise ValueError("PocketBase devolvio una respuesta invalida al cancelar la inscripcion")

        self._client.request("DELETE", f"{self._enrollments_base}/{enrollment_id}")
        return self._get_session_or_raise(session_id)

    def delete(self, session_id: str) -> tuple[TutorialSessionResponse, list[TutorialEnrollmentResponse]] | None:
        session = self.get_by_id(session_id)
        if session is None:
            return None

        for enrollment in self._list_enrollment_records(session_id=session_id):
            enrollment_id = str(enrollment.get("id") or "").strip()
            if enrollment_id:
                self._client.request("DELETE", f"{self._enrollments_base}/{enrollment_id}")

        self._client.request("DELETE", f"{self._sessions_base}/{session_id}")
        return session, list(session.enrolled_students)
