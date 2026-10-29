from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1.endpoints import tutorial_sessions, reservations
from app.application.schedule_conflicts import first_conflict, weekly_windows
from app.application import laboratory_access
from app.core.datetime_utils import now_local_naive
from app.infrastructure.repositories.lab_schedule_repository import LabScheduleRepository
from app.schemas.lab_schedule import LabScheduleResponse
from app.schemas.tutorial_session import TutorialSessionResponse


def event(start, end):
    return SimpleNamespace(laboratory_id="lab-1", is_active=True, start_at=start, end_at=end)


def test_multiday_block_covers_next_week_even_before_its_start_time():
    now = datetime(2026, 10, 26, 18)
    block = event("2026-10-26T17:00:00", "2026-11-10T08:00:00")
    windows = weekly_windows("lab-1", 0, [], [("lab_block", block)], now=now)
    assert first_conflict("07:15", "08:00", windows)["date"] == "2026-11-02"


def test_elapsed_hours_today_do_not_block_future_weekly_classes():
    now = datetime(2026, 10, 26, 18)
    block = event("2026-10-26T07:15:00", "2026-10-26T19:00:00")
    windows = weekly_windows("lab-1", 0, [], [("lab_block", block)], now=now)
    assert first_conflict("07:15", "08:00", windows) is None
    assert first_conflict("18:30", "19:15", windows) is not None


def test_overnight_block_is_projected_onto_both_weekdays():
    block = event("2026-10-26T20:00:00Z", "2026-10-27T09:00:00Z")
    now = datetime(2026, 10, 25)
    monday = weekly_windows("lab-1", 0, [], [("lab_block", block)], now=now)
    tuesday = weekly_windows("lab-1", 1, [], [("lab_block", block)], now=now)
    assert first_conflict("20:15", "21:00", monday)
    assert first_conflict("07:15", "08:00", tuesday)
    assert first_conflict("09:00", "09:45", tuesday) is None


def test_partial_minute_at_block_end_still_blocks_the_next_slot():
    block = event("2026-10-26T07:15:00", "2026-10-26T08:00:01")
    windows = weekly_windows("lab-1", 0, [], [("lab_block", block)], now=datetime(2026, 10, 25))
    assert first_conflict("08:00", "08:45", windows)


@pytest.mark.parametrize("phase", ["create", "update", "approval"])
def test_tutorial_cannot_cross_an_approved_class_at_any_write(monkeypatch, phase):
    day = (now_local_naive() + timedelta(days=7)).date().isoformat()
    session = TutorialSessionResponse(id="tutorial-1", tutor_id="teacher-1", tutor_name="Docente", topic="Repaso",
        description="", laboratory_id="lab-1", location="Laboratorio", session_date=day,
        start_time="09:00", end_time="09:45", start_at=f"{day}T09:00:00", end_at=f"{day}T09:45:00",
        max_students=10, is_published=True, approval_status="pending", created="", updated="")
    create, update, approve = Mock(), Mock(), Mock()
    monkeypatch.setattr(tutorial_sessions, "tutorial_session_repo", SimpleNamespace(
        get_by_id=lambda _: session, create=create, update=update, set_approval_status=approve, validate_for_approval=Mock()))
    monkeypatch.setattr(tutorial_sessions, "ensure_user_can_reserve_laboratory", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tutorial_sessions, "lab_schedule_repo", SimpleNamespace(list_active_for_laboratory_weekday=lambda *_args: [
        SimpleNamespace(start_time="09:00", end_time="10:30")]))
    monkeypatch.setattr(tutorial_sessions, "lab_block_repo", SimpleNamespace(list_for_laboratory_day=lambda *_args: []))
    app = FastAPI()
    app.include_router(tutorial_sessions.router)
    app.dependency_overrides[tutorial_sessions.get_current_user] = lambda: {
        "user_id": "teacher-1", "permissions": ["gestionar_tutorias_propias", "aprobar_tutorias"]}
    body = dict(topic="Repaso", laboratory_id="lab-1", session_date=day, start_time="09:00", end_time="09:45", max_students=10)
    with TestClient(app) as client:
        if phase == "create":
            response = client.post("/tutorial-sessions", json=body)
        elif phase == "update":
            response = client.patch("/tutorial-sessions/tutorial-1", json=body)
        else:
            response = client.patch("/tutorial-sessions/tutorial-1/approval", json={"status": "approved"})
    assert response.status_code == 422
    assert "clase" in response.json()["detail"]
    create.assert_not_called(); update.assert_not_called(); approve.assert_not_called()


def test_pending_student_reservation_cannot_be_approved_over_new_class(monkeypatch):
    day = (now_local_naive() + timedelta(days=7)).date().isoformat()
    monkeypatch.setattr(reservations, "lab_schedule_repo", SimpleNamespace(list_active_for_laboratory_weekday=lambda *_args: [
        SimpleNamespace(start_time="09:00", end_time="10:30")]))
    with pytest.raises(HTTPException) as exc:
        reservations._validate_approval_no_conflict(event(f"{day}T09:00:00", f"{day}T09:45:00"))
    assert exc.value.status_code == 422
    assert "clase" in exc.value.detail


def test_change_uses_one_batch_without_a_nontransactional_fallback():
    original = LabScheduleResponse(id="original", laboratory_id="lab-1", weekday=0, start_time="07:15", end_time="08:00",
        subject="Fisica", description="", teacher_id="teacher-1", is_active=True, created="", updated="")
    proposal = original.model_copy(update={"id": "proposal", "original_schedule_id": "original", "subject": "Quimica", "is_active": False})
    client = SimpleNamespace(request=Mock(side_effect=ValueError("Batch fallo")))
    repo = LabScheduleRepository(client)
    with pytest.raises(ValueError):
        repo.apply_change(proposal, original, {"approval_status": "approved"})
    client.request.assert_called_once()
    args, kwargs = client.request.call_args
    assert args == ("POST", "/api/batch")
    mutations = kwargs["payload"]["requests"]
    assert len(mutations) == 2
    assert mutations[0]["body"]["subject"] == "Quimica"
    assert mutations[0]["body"]["is_active"] is True
    assert mutations[1]["body"]["is_active"] is False


def test_tutorial_approver_does_not_need_class_approval_permission(monkeypatch):
    monkeypatch.setattr(laboratory_access, "laboratory_access_repo", SimpleNamespace(get_by_id=lambda _: {"id": "lab-1", "is_active": True}))
    actor = {"permissions": ["aprobar_tutorias"]}
    assert laboratory_access.ensure_user_can_reserve_laboratory("lab-1", actor, approval=True, approval_permission="aprobar_tutorias")["id"] == "lab-1"
    with pytest.raises(HTTPException) as exc:
        laboratory_access.ensure_user_can_reserve_laboratory("lab-1", actor, approval=True)
    assert exc.value.status_code == 403
