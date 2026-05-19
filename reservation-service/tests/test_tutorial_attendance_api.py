from __future__ import annotations

from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.v1.endpoints import tutorial_sessions as tutorial_sessions_endpoints
from app.core.dependencies import get_current_user
from app.schemas.tutorial_session import TutorialEnrollmentResponse, TutorialSessionResponse


def _session_with_students(*students: TutorialEnrollmentResponse) -> TutorialSessionResponse:
    return TutorialSessionResponse(
        id="session-1",
        tutor_id="tutor-1",
        tutor_name="Tutor Uno",
        tutor_email="tutor1@ucb.edu.bo",
        topic="Tutoria de Calculo",
        description="Repaso de derivadas",
        laboratory_id="lab-1",
        location="Laboratorio 101",
        session_date="2026-05-20",
        start_time="10:00",
        end_time="11:00",
        start_at="2026-05-20T10:00:00Z",
        end_at="2026-05-20T11:00:00Z",
        max_students=20,
        is_published=True,
        tutor_observation="",
        enrolled_students=list(students),
        created="2026-05-01T00:00:00Z",
        updated="2026-05-01T00:00:00Z",
    )


class _StubTutorialRepo:
    def __init__(self) -> None:
        self.session = _session_with_students(
            TutorialEnrollmentResponse(
                student_id="student-1",
                student_name="Ana Perez",
                student_email="ana@ucb.edu.bo",
                created_at="2026-05-15T09:00:00Z",
                attended=False,
                performance_observation="",
            )
        )
        self.calls: list[tuple[str, dict]] = []

    def get_by_id(self, session_id: str):
        if session_id != self.session.id:
            return None
        return self.session

    def save_enrollment_attendance(self, session_id: str, *, student_id: str, attended: bool, performance_observation: str):
        self.calls.append((
            "save_enrollment_attendance",
            {
                "session_id": session_id,
                "student_id": student_id,
                "attended": attended,
                "performance_observation": performance_observation,
            },
        ))
        if student_id != "student-1":
            raise ValueError("No se encontro una inscripcion activa para esta tutoria")

        updated_student = self.session.enrolled_students[0].model_copy(
            update={
                "attended": attended,
                "performance_observation": performance_observation,
            }
        )
        self.session = self.session.model_copy(
            update={
                "enrolled_students": [updated_student],
            }
        )
        return self.session


def _build_client(repo: _StubTutorialRepo) -> TestClient:
    app = FastAPI()
    app.include_router(tutorial_sessions_endpoints.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "tutor-1",
        "permissions": ["gestionar_tutorias", "gestionar_observaciones_tutorias"],
        "role": "tutor",
    }
    tutorial_sessions_endpoints.tutorial_session_repo = repo
    return TestClient(app)


def test_tutor_updates_attendance_for_active_enrollment() -> None:
    repo = _StubTutorialRepo()
    client = _build_client(repo)

    response = client.patch(
        "/api/v1/tutorial-sessions/session-1/attendance/student-1",
        json={
            "attended": True,
            "performance_observation": "Participa con seguridad y resolvio ejercicios clave.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["enrolled_students"]) == 1
    assert payload["enrolled_students"][0]["student_id"] == "student-1"
    assert payload["enrolled_students"][0]["attended"] is True
    assert payload["enrolled_students"][0]["performance_observation"] == "Participa con seguridad y resolvio ejercicios clave."
    assert repo.calls[0][1]["student_id"] == "student-1"


def test_tutor_cannot_register_attendance_for_missing_enrollment() -> None:
    repo = _StubTutorialRepo()
    client = _build_client(repo)

    response = client.patch(
        "/api/v1/tutorial-sessions/session-1/attendance/student-404",
        json={
            "attended": True,
            "performance_observation": "No deberia guardarse.",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "No se encontro una inscripcion activa para esta tutoria"


def test_tutor_observation_is_limited_to_200_characters() -> None:
    repo = _StubTutorialRepo()
    client = _build_client(repo)

    response = client.patch(
        "/api/v1/tutorial-sessions/session-1/attendance/student-1",
        json={
            "attended": False,
            "performance_observation": "x" * 201,
        },
    )

    assert response.status_code == 422