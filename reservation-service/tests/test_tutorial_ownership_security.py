import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import tutorial_sessions
from app.schemas.tutorial_session import TutorialSessionCreate, TutorialSessionResponse


def _session(*, tutor_id: str = "tutor-b", published: bool = False) -> TutorialSessionResponse:
    return TutorialSessionResponse(
        id="tutorial-1",
        tutor_id=tutor_id,
        tutor_name="Tutor",
        tutor_email="tutor@ucb.edu.bo",
        topic="Calculo seguro",
        description="Repaso",
        laboratory_id="lab-1",
        location="Laboratorio 1",
        session_date="2026-11-10",
        start_time="10:00",
        end_time="11:00",
        start_at="2026-11-10T10:00:00",
        end_at="2026-11-10T11:00:00",
        max_students=10,
        is_published=published,
        created="2026-10-24T00:00:00Z",
        updated="2026-10-24T00:00:00Z",
    )


def test_create_tutorial_ignores_forged_tutor_identity(monkeypatch) -> None:
    captured = {}

    def create(payload):
        captured.update(payload.model_dump())
        return _session(tutor_id=payload.tutor_id)

    monkeypatch.setattr(tutorial_sessions, "tutorial_session_repo", SimpleNamespace(create=create))
    monkeypatch.setattr(tutorial_sessions, "_invalidate_tutorial_availability", lambda _session: None)
    monkeypatch.setattr(tutorial_sessions, "realtime_manager", SimpleNamespace(broadcast=AsyncMock()))

    body = TutorialSessionCreate(
        topic="Calculo seguro",
        laboratory_id="lab-1",
        location="Laboratorio 1",
        session_date="2026-11-10",
        start_time="10:00",
        end_time="11:00",
        max_students=10,
        tutor_id="tutor-b",
        tutor_name="Tutor B",
        tutor_email="tutor-b@ucb.edu.bo",
    )
    actor = {
        "user_id": "tutor-a",
        "name": "Tutor A",
        "username": "tutor-a@ucb.edu.bo",
        "email": "tutor-a@ucb.edu.bo",
        "permissions": ["gestionar_tutorias_propias"],
    }

    asyncio.run(tutorial_sessions.create_tutorial_session(body, actor))

    assert captured["tutor_id"] == "tutor-a"
    assert captured["tutor_name"] == "Tutor A"
    assert captured["tutor_email"] == "tutor-a@ucb.edu.bo"


def test_tutor_cannot_read_another_tutors_private_session(monkeypatch) -> None:
    monkeypatch.setattr(
        tutorial_sessions,
        "tutorial_session_repo",
        SimpleNamespace(get_by_id=lambda _session_id: _session(tutor_id="tutor-b")),
    )

    with pytest.raises(HTTPException) as exc:
        tutorial_sessions.get_tutorial_session(
            "tutorial-1",
            {"user_id": "tutor-a", "permissions": ["gestionar_tutorias_propias"]},
        )

    assert exc.value.status_code == 403


def test_approver_can_read_private_session(monkeypatch) -> None:
    expected = _session(tutor_id="tutor-b")
    monkeypatch.setattr(
        tutorial_sessions,
        "tutorial_session_repo",
        SimpleNamespace(get_by_id=lambda _session_id: expected),
    )

    result = tutorial_sessions.get_tutorial_session(
        "tutorial-1",
        {"user_id": "approver-1", "permissions": ["aprobar_tutorias"]},
    )

    assert result.id == expected.id
