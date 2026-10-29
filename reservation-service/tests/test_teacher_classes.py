from types import SimpleNamespace
from datetime import timedelta
from unittest.mock import AsyncMock, Mock
from concurrent.futures import ThreadPoolExecutor

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

    def list_for_laboratory(self, lab):
        return [r for r in self.records.values() if r.laboratory_id == lab]

    def pending_change(self, key):
        return next((r for r in self.records.values() if r.original_schedule_id == key and r.approval_status == "pending"), None)

    def save_change(self, previous, body):
        if previous is None:
            return self.create(body)
        self.records[previous.id] = previous.model_copy(update=body.model_dump(exclude_none=True))
        return self.records[previous.id]

    def apply_change(self, proposal, original, decision):
        fields = {key: getattr(proposal, key) for key in schedules.EDITABLE}
        self.records[original.id] = original.model_copy(update={**fields, **decision, "is_active": True})
        self.records[proposal.id] = proposal.model_copy(update={**decision, "is_active": False})
        return self.records[proposal.id]

    def resolve_teacher(self, teacher_id):
        if teacher_id and teacher_id != "teacher-1":
            raise ValueError("Selecciona un usuario activo con rol Docente")
        return "Docente" if teacher_id else ""

    def delete(self, key):
        return self.records.pop(key, None) is not None

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
    result = client.post("/lab-schedules", json={**PAYLOAD, "teacher_id": "someone-else", "approval_status": "approved", "is_active": True, "approved_by": "admin", "original_schedule_id": "another-class", "original_snapshot": {"subject": "Falsa"}})
    assert result.status_code == 201
    assert result.json()["teacher_id"] == "teacher-1"
    assert result.json()["approval_status"] == "pending"
    assert result.json()["is_active"] is False
    assert result.json()["approved_by"] == ""
    assert result.json()["original_schedule_id"] == ""
    assert result.json()["original_snapshot"] == {}
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
    client, repo, actor = context
    key = client.post("/lab-schedules", json=PAYLOAD).json()["id"]
    actor.clear(); actor.update(ADMIN)
    assert client.patch(f"/lab-schedules/{key}/approval", json={"status": "approved"}).status_code == 200
    actor.clear(); actor.update(TEACHER)
    result = client.patch(f"/lab-schedules/{key}", json={"subject": "Quimica", "approval_status": "approved", "teacher_id": "admin-1"})
    assert result.status_code == 200
    assert result.json()["teacher_id"] == "teacher-1"
    assert result.json()["approval_status"] == "pending"
    assert result.json()["is_active"] is False
    assert result.json()["original_schedule_id"] == key
    assert repo.get_by_id(key).subject == "Fisica"
    assert repo.get_by_id(key).is_active is True
    assert repo.get_by_id(key).approval_status == "approved"
    actor["user_id"] = "other-teacher"
    assert client.patch(f"/lab-schedules/{key}", json={"subject": "Otra"}).status_code == 403
    assert client.get("/lab-schedules?teacher_id=teacher-1").status_code == 403


def approved_class(context):
    client, repo, actor = context
    key = client.post("/lab-schedules", json=PAYLOAD).json()["id"]
    actor.clear(); actor.update(ADMIN)
    assert client.patch(f"/lab-schedules/{key}/approval", json={"status": "approved"}).status_code == 200
    actor.clear(); actor.update(TEACHER)
    return key


def test_one_pending_change_can_be_updated_and_withdrawn(context):
    client, repo, _ = context
    key = approved_class(context)
    first = client.patch(f"/lab-schedules/{key}", json={"subject": "Quimica", "start_time": "09:00", "end_time": "09:45"}).json()
    second = client.patch(f"/lab-schedules/{key}", json={"subject": "Biologia"}).json()
    assert first["id"] == second["id"]
    assert second["start_time"] == "09:00" and second["end_time"] == "09:45"
    assert len(repo.list_pending()) == 1
    assert repo.get_by_id(key).subject == "Fisica"
    assert client.delete(f"/lab-schedules/{first['id']}").status_code == 204
    assert set(schedules.realtime_manager.broadcast.call_args.args[0]["record"]) == {"id", "laboratory_id"}
    assert repo.list_pending() == []
    assert repo.get_by_id(key).is_active


@pytest.mark.parametrize("decision", ["approved", "rejected"])
def test_decision_on_change_preserves_original_identity_and_occupancy(context, decision):
    client, repo, actor = context
    key = approved_class(context)
    change = client.patch(f"/lab-schedules/{key}", json={"start_time": "09:00", "end_time": "09:45"}).json()
    assert repo.list_active_for_laboratory_weekday("lab-1", 0)[0].start_time == "07:15"
    actor.clear(); actor.update(ADMIN)
    result = client.patch(f"/lab-schedules/{change['id']}/approval", json={"status": decision, "reason": "Revisado"})
    assert result.status_code == 200
    original = repo.get_by_id(key)
    assert original.is_active and original.approval_status == "approved"
    assert original.start_time == ("09:00" if decision == "approved" else "07:15")
    assert len(repo.list_active_for_laboratory_weekday("lab-1", 0)) == 1
    assert repo.get_by_id(change["id"]).is_active is False


def test_stale_change_cannot_overwrite_admin_edit(context):
    client, repo, actor = context
    key = approved_class(context)
    change = client.patch(f"/lab-schedules/{key}", json={"subject": "Quimica"}).json()
    actor.clear(); actor.update(ADMIN)
    assert client.patch(f"/lab-schedules/{key}", json={"subject": "Actualizada por admin"}).status_code == 200
    pending = client.get("/lab-schedules/pending").json()[0]
    assert pending["source_changed"] is True
    assert pending["current_schedule"]["subject"] == "Actualizada por admin"
    assert pending["original_snapshot"]["subject"] == "Fisica"
    result = client.patch(f"/lab-schedules/{change['id']}/approval", json={"status": "approved"})
    assert result.status_code == 409
    assert repo.get_by_id(key).subject == "Actualizada por admin"
    actor.clear(); actor.update(TEACHER)
    assert client.patch(f"/lab-schedules/{key}", json={"subject": "Nueva propuesta"}).status_code == 200
    actor.clear(); actor.update(ADMIN)
    assert client.patch(f"/lab-schedules/{change['id']}/approval", json={"status": "approved"}).status_code == 200


def test_failed_change_does_not_release_original(context, monkeypatch):
    client, repo, actor = context
    key = approved_class(context)
    change = client.patch(f"/lab-schedules/{key}", json={"subject": "Quimica"}).json()
    before = repo.get_by_id(key).model_dump()
    monkeypatch.setattr(repo, "apply_change", Mock(side_effect=ValueError("No se pudo confirmar")))
    actor.clear(); actor.update(ADMIN)
    # Un fallo de persistencia deja la solicitud pendiente y la clase intacta.
    assert client.patch(f"/lab-schedules/{change['id']}/approval", json={"status": "approved"}).status_code == 503
    assert repo.get_by_id(key).model_dump() == before
    assert repo.get_by_id(change["id"]).approval_status == "pending"


def test_admin_creates_approved_and_teacher_selection_is_validated(context):
    client, repo, actor = context
    actor.clear(); actor.update(ADMIN)
    response = client.post("/lab-schedules", json={**PAYLOAD, "teacher_id": "teacher-1", "teacher_name": "Falso"})
    assert response.status_code == 201
    assert response.json()["approval_status"] == "approved" and response.json()["is_active"]
    assert response.json()["teacher_name"] == "Docente"
    assert client.post("/lab-schedules", json={**PAYLOAD, "teacher_id": "student-1"}).status_code == 422


def test_availability_and_submission_share_conflicts_and_authorized_exclusion(context):
    client, repo, actor = context
    key = approved_class(context)
    query = f"/lab-schedules/availability?laboratory_id=lab-1&weekday=0"
    assert client.get(query).json()["slots"][0]["state"] == "blocked"
    assert client.post("/lab-schedules", json=PAYLOAD).status_code == 409
    assert client.get(query + f"&exclude_id={key}").json()["slots"][0]["state"] == "available"
    actor["user_id"] = "another-teacher"
    assert client.get(query + f"&exclude_id={key}").status_code == 403


def test_conflict_inside_a_multi_block_range_is_rejected(context, monkeypatch):
    client, _, _ = context
    day = now_local_naive() + timedelta(days=7)
    block = SimpleNamespace(laboratory_id="lab-1", is_active=True,
        start_at=day.replace(hour=8, minute=45, second=0, microsecond=0).isoformat(),
        end_at=day.replace(hour=9, minute=0, second=0, microsecond=0).isoformat())
    monkeypatch.setattr(schedules, "lab_block_repo", SimpleNamespace(list_all=lambda: [block]))
    body = {**PAYLOAD, "weekday": day.weekday(), "end_time": "09:45"}
    assert client.post("/lab-schedules", json=body).status_code == 409
    data = client.get(f"/lab-schedules/availability?laboratory_id=lab-1&weekday={day.weekday()}").json()
    assert data["slots"][0]["state"] == data["slots"][2]["state"] == "available"
    assert data["blocked_ranges"][0]["date"] == day.date().isoformat()


def test_overlapping_class_cannot_be_approved(context):
    client, _, actor = context
    first = client.post("/lab-schedules", json=PAYLOAD).json()["id"]
    second = client.post("/lab-schedules", json=PAYLOAD).json()["id"]
    actor.clear(); actor.update(ADMIN)
    assert client.patch(f"/lab-schedules/{first}/approval", json={"status": "approved"}).status_code == 200
    assert client.patch(f"/lab-schedules/{second}/approval", json={"status": "approved"}).status_code == 409


def test_concurrent_approvals_commit_only_one_class(context):
    client, repo, actor = context
    with client:
        keys = [client.post("/lab-schedules", json=PAYLOAD).json()["id"] for _ in range(2)]
        actor.clear(); actor.update(ADMIN)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda key: client.patch(f"/lab-schedules/{key}/approval", json={"status": "approved"}).status_code, keys))
    assert sorted(results) == [200, 409]
    assert len(repo.list_active_for_laboratory_weekday("lab-1", 0)) == 1


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
