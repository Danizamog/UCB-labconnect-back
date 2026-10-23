from types import SimpleNamespace
from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import schedules
from app.schemas.lab_schedule import LabScheduleResponse
from app.core.datetime_utils import now_local_naive


TEACHER = {"user_id": "teacher-1", "name": "Docente", "role": "Docente", "permissions": ["gestionar_clases_propias", "solicitar_recursos_clase"]}
ADMIN = {"user_id": "admin-1", "role": "Administrador", "permissions": ["gestionar_horarios_laboratorio", "aprobar_clases"]}
MANAGER = {"user_id": "manager-1", "role": "Encargado de Laboratorio", "permissions": ["gestionar_reservas", "gestionar_accesos_laboratorio"]}
PAYLOAD = {"laboratory_id": "lab-1", "weekday": 0, "start_time": "07:15", "end_time": "08:00", "subject": "Fisica"}


class MemorySchedules:
    def __init__(self):
        self.records = {}

    def create(self, body):
        data = body.model_dump(exclude_none=True)
        item = LabScheduleResponse(**{**data, "id": f"class-{len(self.records) + 1}", "description": data.get("description", ""), "created": "", "updated": ""})
        self.records[item.id] = item
        return item

    def get_by_id(self, key):
        return self.records.get(key)

    def update(self, key, body):
        self.records[key] = self.records[key].model_copy(update=body.model_dump(exclude_none=True))
        return self.records[key]

    def list_all(self):
        return list(self.records.values())

    def list_pending(self):
        return [r for r in self.records.values() if r.approval_status == "pending"]

    def list_for_teacher(self, teacher_id):
        return [r for r in self.records.values() if r.teacher_id == teacher_id]

    def list_active_for_laboratory_weekday(self, lab, weekday):
        return [r for r in self.records.values() if r.laboratory_id == lab and r.weekday == weekday and r.is_active and r.approval_status == "approved"]


@pytest.fixture
def context(monkeypatch):
    repo = MemorySchedules()
    monkeypatch.setattr(schedules, "lab_schedule_repo", repo)
    for name in ("lab_reservation_repo", "tutorial_session_repo", "lab_block_repo"):
        monkeypatch.setattr(schedules, name, SimpleNamespace(list_all=lambda **kwargs: []))
    monkeypatch.setattr(schedules, "ensure_user_can_reserve_laboratory", Mock(return_value={"id": "lab-1"}))
    monkeypatch.setattr(schedules, "invalidate_availability_cache", Mock())
    monkeypatch.setattr(schedules, "realtime_manager", SimpleNamespace(broadcast=AsyncMock()))
    app = FastAPI()
    app.include_router(schedules.router)
    actor = dict(TEACHER)
    app.dependency_overrides[schedules.get_current_user] = lambda: actor
    return TestClient(app), repo, actor


def test_teacher_creates_own_pending_class_even_with_forged_approval(context):
    client, repo, _ = context
    result = client.post("/lab-schedules", json={**PAYLOAD, "teacher_id": "someone-else", "approval_status": "approved", "is_active": True, "approved_by": "admin"})
    assert result.status_code == 201
    assert result.json()["teacher_id"] == "teacher-1"
    assert result.json()["approval_status"] == "pending"
    assert result.json()["is_active"] is False
    assert result.json()["approved_by"] == ""
    assert repo.list_active_for_laboratory_weekday("lab-1", 0) == []
    assert len(client.get("/lab-schedules?teacher_id=me").json()) == 1


@pytest.mark.parametrize("user", [TEACHER, MANAGER])
def test_teacher_and_lab_manager_cannot_approve_or_list_pending(context, user):
    client, _, actor = context
    actor.clear(); actor.update(user)
    assert client.get("/lab-schedules/pending").status_code == 403
    assert client.patch("/lab-schedules/class-1/approval", json={"status": "approved"}).status_code == 403


def test_admin_approves_and_prevents_duplicate_decision(context):
    client, repo, actor = context
    created = client.post("/lab-schedules", json=PAYLOAD).json()
    actor.clear(); actor.update(ADMIN)
    assert len(client.get("/lab-schedules/pending").json()) == 1
    approved = client.patch(f"/lab-schedules/{created['id']}/approval", json={"status": "approved"})
    assert approved.status_code == 200
    assert approved.json()["approved_by"] == "admin-1"
    assert len(repo.list_active_for_laboratory_weekday("lab-1", 0)) == 1
    assert client.patch(f"/lab-schedules/{created['id']}/approval", json={"status": "approved"}).status_code == 409


def test_rejection_requires_reason_and_teacher_sees_it(context):
    client, _, actor = context
    key = client.post("/lab-schedules", json=PAYLOAD).json()["id"]
    actor.clear(); actor.update(ADMIN)
    assert client.patch(f"/lab-schedules/{key}/approval", json={"status": "rejected"}).status_code == 422
    result = client.patch(f"/lab-schedules/{key}/approval", json={"status": "rejected", "reason": "Sin disponibilidad"})
    assert result.status_code == 200
    actor.clear(); actor.update(TEACHER)
    own = client.get("/lab-schedules?teacher_id=me").json()
    assert own[0]["approval_reason"] == "Sin disponibilidad"
    assert own[0]["is_active"] is False


def test_teacher_edit_requires_new_approval_and_cannot_change_owner(context):
    client, _, actor = context
    key = client.post("/lab-schedules", json=PAYLOAD).json()["id"]
    actor.clear(); actor.update(ADMIN)
    assert client.patch(f"/lab-schedules/{key}/approval", json={"status": "approved"}).status_code == 200
    actor.clear(); actor.update(TEACHER)
    result = client.patch(f"/lab-schedules/{key}", json={"subject": "Quimica", "approval_status": "approved", "teacher_id": "admin-1"})
    assert result.status_code == 200
    assert result.json()["teacher_id"] == "teacher-1"
    assert result.json()["approval_status"] == "pending"
    assert result.json()["is_active"] is False
    actor["user_id"] = "other-teacher"
    assert client.patch(f"/lab-schedules/{key}", json={"subject": "Otra"}).status_code == 403
    assert client.get("/lab-schedules?teacher_id=teacher-1").status_code == 403


def test_overlapping_class_cannot_be_approved(context):
    client, _, actor = context
    first = client.post("/lab-schedules", json=PAYLOAD).json()["id"]
    second = client.post("/lab-schedules", json=PAYLOAD).json()["id"]
    actor.clear(); actor.update(ADMIN)
    assert client.patch(f"/lab-schedules/{first}/approval", json={"status": "approved"}).status_code == 200
    assert client.patch(f"/lab-schedules/{second}/approval", json={"status": "approved"}).status_code == 409


def test_manager_cannot_bypass_approval_by_creating_schedule(context):
    client, _, actor = context
    actor.clear(); actor.update(MANAGER)
    assert client.post("/lab-schedules", json=PAYLOAD).status_code == 403


def test_pending_not_public_and_invalid_partial_time_rejected(context):
    client, _, _ = context
    key = client.post("/lab-schedules", json=PAYLOAD).json()["id"]
    assert client.get("/lab-schedules").json() == []
    assert client.patch(f"/lab-schedules/{key}", json={"start_time": "09:00"}).status_code == 422


@pytest.mark.parametrize("repository,state", [("lab_reservation_repo", "approved"), ("tutorial_session_repo", "approved"), ("lab_block_repo", None)])
def test_approval_rejects_preexisting_reservation_tutorial_or_block(context, monkeypatch, repository, state):
    client, _, actor = context
    day = now_local_naive() + timedelta(days=7)
    key = client.post("/lab-schedules", json={**PAYLOAD, "weekday": day.weekday()}).json()["id"]
    record = {"laboratory_id": "lab-1", "start_at": day.replace(hour=7, minute=15).isoformat(), "end_at": day.replace(hour=8, minute=0).isoformat()}
    if repository == "tutorial_session_repo":
        record["approval_status"] = state
    elif state:
        record.update(status=state, is_active=True)
    else:
        record["is_active"] = True
    monkeypatch.setattr(schedules, repository, SimpleNamespace(list_all=lambda **kwargs: [SimpleNamespace(**record)]))
    actor.clear(); actor.update(ADMIN)
    assert client.patch(f"/lab-schedules/{key}/approval", json={"status": "approved"}).status_code == 409
