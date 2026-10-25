import os
os.environ.setdefault("SECRET_KEY", "isolated-rbac-tests")
os.environ["POCKETBASE_URL"] = ""

from copy import deepcopy
from datetime import date
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.application.use_cases.manage_roles import ManageRolesUseCase
from app.domain.entities.role import Role
from app.core.dependencies import get_current_user_payload
from app.infrastructure.repositories.in_memory_role_repository import InMemoryRoleRepository
from app.infrastructure.repositories.pocketbase_role_repository import PocketBaseRoleRepository
from app.interfaces.http import router
from app.main import app

ACTOR = {"user_id": "manager", "username": "manager@ucb.edu.bo", "role": "Administrador de Accesos",
         "permissions": ["gestionar_roles", "asignar_roles", "consultar_roles", "revisar_accesos_rbac"]}
REASON = "Cambio autorizado para pruebas RBAC"


@pytest.fixture
def context(monkeypatch):
    repo = InMemoryRoleRepository()
    use_case = ManageRolesUseCase(repo)
    use_case.ensure_default_roles()
    roles = {role.nombre: role for role in repo.list_all()}
    repo._users = {key: {"id": key, "email": f"{key}@ucb.edu.bo", "name": key,
                         "is_active": True, "roleId": roles[role].id}
                   for key, role in [("manager", "Administrador de Accesos"), ("backup", "Administrador de Accesos"),
                                     ("target", "Estudiante"), ("admin", "Administrador")]}
    monkeypatch.setattr(router, "manage_roles_use_case", use_case)
    app.dependency_overrides[get_current_user_payload] = lambda: deepcopy(ACTOR)
    yield use_case, repo, roles, TestClient(app)
    app.dependency_overrides.clear()


@pytest.mark.parametrize("role_name", ["Administrador", "Administrador de Accesos", "OSI - Auditor de Seguridad", "Docente"])
def test_any_role_can_be_assigned_and_its_previous_state_is_audited(context, role_name):
    use_case, repo, roles, _ = context
    result = use_case.assign_user_role("target", roles[role_name].id, actor=ACTOR, reason=REASON)
    assert result["role"]["nombre"] == role_name
    event = repo._history[0]
    assert event["actor_id"] == "manager"
    assert event["actor_email"] == ACTOR["username"]
    assert event["before"]["role_name"] == "Estudiante"
    assert event["after"]["role_name"] == role_name
    assert event["target_user_id"] == "target" and event["reason"] == REASON


def test_privileged_account_can_be_reassigned_and_self_change_is_allowed_with_backup(context):
    use_case, _, roles, _ = context
    assert use_case.assign_user_role("admin", roles["Docente"].id, actor=ACTOR, reason=REASON)["role"]["nombre"] == "Docente"
    assert use_case.assign_user_role("manager", roles["Estudiante"].id, actor=ACTOR, reason=REASON)["role"]["nombre"] == "Estudiante"


def test_last_access_manager_cannot_be_removed(context):
    use_case, repo, roles, _ = context
    repo._users["backup"]["is_active"] = False
    with pytest.raises(ValueError, match="al menos una cuenta activa"):
        use_case.assign_user_role("manager", roles["Estudiante"].id, actor=ACTOR, reason=REASON)
    assert repo._history == []


def test_last_access_role_cannot_lose_management_permissions(context):
    use_case, repo, roles, _ = context
    role = repo.create(Role(id='', nombre='Gestor delegado', descripcion='', permisos=['gestionar_roles', 'asignar_roles']))
    repo._users['manager']['roleId'] = role.id
    repo._users['backup']['roleId'] = role.id
    before = deepcopy(role.permisos)
    with pytest.raises(ValueError, match="al menos una cuenta activa"):
        use_case.update_role(role.id, role.nombre, "Cambio", ["consultar_roles"], actor=ACTOR, reason=REASON)
    assert repo.get_by_id(role.id).permisos == before
    assert repo._history == []


@pytest.mark.parametrize("name", ["Docente", "OSI - Auditor de Seguridad"])
def test_other_roles_remain_editable_with_granular_permissions(context, name):
    use_case, repo, roles, _ = context
    role = roles[name]
    permissions = sorted(set(role.permisos) | {"reiniciar_credenciales"})
    updated = use_case.update_role(role.id, role.nombre, "Nueva descripcion", permissions, actor=ACTOR, reason=REASON)
    assert "reiniciar_credenciales" in updated.permisos
    assert repo._history[0]["before"]["descripcion"] != "Nueva descripcion"
    assert repo._history[0]["after"]["descripcion"] == "Nueva descripcion"


def test_custom_role_can_receive_management_permissions(context):
    use_case, repo, _, _ = context
    role = use_case.create_role("Coordinador de accesos", "Delegado", ["asignar_roles"], actor=ACTOR, reason=REASON)
    assert role.permisos == ["asignar_roles"]
    assert repo._history[0]["role_id"] == role.id


def test_legacy_permissions_can_be_preserved_or_removed_but_not_invented(context):
    use_case, repo, roles, _ = context
    role = roles["Docente"]
    role.permisos.append("permiso_heredado")
    result = use_case.update_role(role.id, role.nombre, "Legacy", role.permisos, actor=ACTOR, reason=REASON)
    assert "permiso_heredado" in result.permisos
    with pytest.raises(ValueError, match="Permisos invalidos"):
        use_case.update_role(role.id, role.nombre, "Legacy", ["inventado"], actor=ACTOR, reason=REASON)


def test_rename_base_role_is_rejected_to_preserve_academic_flows(context):
    use_case, _, roles, _ = context
    with pytest.raises(ValueError, match="nombre de los perfiles base"):
        use_case.update_role(roles["Docente"].id, "Otro nombre", "", [], actor=ACTOR, reason=REASON)


@pytest.mark.parametrize('name', ['Administrador', 'Administrador de Accesos'])
@pytest.mark.parametrize('method', ['put', 'patch'])
def test_admin_role_configuration_is_locked_in_the_api_without_mutating_or_auditing(context, name, method):
    _, repo, roles, client = context
    role = roles[name]
    previous = deepcopy(role)
    result = getattr(client, method)(f'/v1/roles/{role.id}', json={
        'nombre': name, 'descripcion': 'Cambio que debe bloquearse', 'permisos': [], 'reason': REASON,
    })
    assert result.status_code == 403
    assert 'protegida' in result.json()['detail']
    assert repo.get_by_id(role.id) == previous
    assert repo._history == []


def test_custom_role_cannot_be_deleted_while_assigned_and_history_survives_deletion(context):
    use_case, repo, _, _ = context
    role = use_case.create_role("Apoyo", "", [], actor=ACTOR, reason=REASON)
    use_case.assign_user_role("target", role.id, actor=ACTOR, reason=REASON)
    with pytest.raises(ValueError, match="Reasigna"):
        use_case.delete_role(role.id, actor=ACTOR, reason=REASON)
    use_case.assign_user_role("target", None, actor=ACTOR, reason=REASON)
    use_case.delete_role(role.id, actor=ACTOR, reason=REASON)
    assert repo.get_by_id(role.id) is None
    assert repo._history[0]["before"]["nombre"] == "Apoyo"
    assert len(repo._history) == 4


def test_audit_failure_prevents_mutation(context, monkeypatch):
    use_case, repo, roles, _ = context
    monkeypatch.setattr(repo, "apply_change", Mock(side_effect=RuntimeError("Audit unavailable")))
    before = deepcopy(roles["Docente"])
    with pytest.raises(RuntimeError):
        use_case.update_role(before.id, before.nombre, "Otro", ["gestionar_roles"], actor=ACTOR, reason=REASON)
    assert repo.get_by_id(before.id) == before


def test_api_uses_authenticated_actor_and_requires_reason(context):
    _, repo, roles, client = context
    url = "/v1/roles/users/target"
    assert client.patch(url, json={"roleId": roles["Administrador"].id}).status_code == 422
    result = client.patch(url, json={"roleId": roles["Administrador"].id, "reason": REASON, "actor_id": "forged", "actor_email": "forged@ucb.edu.bo"})
    assert result.status_code == 200, result.text
    assert repo._history[0]["actor_id"] == ACTOR["user_id"]


def test_read_only_auditor_can_read_but_cannot_change_roles(context):
    _, _, roles, client = context
    app.dependency_overrides[get_current_user_payload] = lambda: {**ACTOR, "permissions": ["revisar_accesos_rbac"]}
    assert client.get("/v1/roles/history").status_code == 200
    assert client.patch("/v1/roles/users/target", json={"roleId": roles["Docente"].id, "reason": REASON}).status_code == 403
    assert client.put(f"/v1/roles/{roles['Administrador'].id}", json={"nombre": "Administrador", "permisos": [], "reason": REASON}).status_code == 403


def test_history_filters_pagination_and_no_edit_delete_endpoint(context):
    use_case, _, roles, client = context
    use_case.assign_user_role("target", roles["Docente"].id, actor=ACTOR, reason=REASON)
    use_case.assign_user_role("target", roles["Invitado"].id, actor=ACTOR, reason=REASON)
    result = client.get("/v1/roles/history?per_page=1&query=manager@ucb.edu.bo").json()
    assert result["totalItems"] == 2 and len(result["items"]) == 1
    assert client.get("/v1/roles/history?action=role.created").json()["totalItems"] == 0
    assert client.get("/v1/roles/history?date_from=2026-11-10&date_to=2026-10-10").status_code == 400
    assert client.get("/v1/roles/history?page=0").status_code == 422
    assert client.delete("/v1/roles/history/event").status_code == 404
    assert client.put("/v1/roles/history/event", json={}).status_code == 404


def test_missing_identity_or_permission_is_rejected(context):
    use_case, _, roles, _ = context
    for actor in ({**ACTOR, "permissions": []}, {**ACTOR, "user_id": ""}):
        with pytest.raises(PermissionError):
            use_case.assign_user_role("target", roles["Docente"].id, actor=actor, reason=REASON)


def test_pocketbase_batches_assignment_and_audit_in_one_transaction(monkeypatch):
    repo = PocketBaseRoleRepository("https://unused.invalid")
    request = Mock(return_value=[{"status": 200, "body": {"id": "target", "email": "target@ucb.edu.bo", "role": "new"}}, {"status": 200, "body": {"id": "event"}}])
    monkeypatch.setattr(repo, "_request", request)
    try:
        repo.apply_change("assign", {"actor_id": "manager", "reason": REASON}, user_id="target", role_id="new")
        assert request.call_count == 1
        operations = request.call_args.kwargs["json"]["requests"]
        assert operations[0]["body"] == {"role": "new"}
        assert operations[1]["url"].endswith("role_change_history/records")
    finally:
        repo.close()


def test_history_dates_filter_bolivian_day_instead_of_utc_day():
    repo = InMemoryRoleRepository()
    repo._history = [{"id": "event", "action": "role.updated", "created": "2026-10-25T01:30:00+00:00"}]
    assert repo.list_history(date_from=date(2026, 10, 24), date_to=date(2026, 10, 24))["totalItems"] == 1
    assert repo.list_history(date_from=date(2026, 10, 25))["totalItems"] == 0


def test_pocketbase_history_filters_escape_input_and_use_bolivian_dates(monkeypatch):
    repo = PocketBaseRoleRepository("https://unused.invalid")
    request = Mock(return_value={"items": []})
    monkeypatch.setattr(repo, "_request", request)
    try:
        repo.list_history(query='" || id != "', date_from=date(2026, 10, 24), date_to=date(2026, 10, 24))
        expression = request.call_args.kwargs["params"]["filter"]
        assert '\\" || id != \\"' in expression
        assert '2026-10-24 04:00:00Z' in expression
        assert '2026-10-25 04:00:00Z' in expression
    finally:
        repo.close()


def test_role_history_snapshot_keeps_pages_stable_when_new_changes_arrive(context):
    use_case, repo, _, client = context
    from datetime import datetime, timedelta, timezone
    created = datetime.now(timezone.utc) - timedelta(minutes=2)
    for i in range(65):
        repo._history.append({'id':f'event-{i:03}', 'action':'role.updated', 'role_name':'Docente',
                              'created':(created+timedelta(seconds=65-i)).isoformat()})
    first = client.get('/v1/roles/history?per_page=20').json()
    assert first['totalItems']==65 and first['totalPages']==4
    repo._history.insert(0, {'id':'new', 'action':'role.updated', 'role_name':'Docente',
                            'created':(datetime.fromisoformat(first['snapshotAt'])+timedelta(seconds=1)).isoformat()})
    second = client.get('/v1/roles/history',params={'per_page':20,'page':2,'snapshot_at':first['snapshotAt']}).json()
    assert second['totalItems']==65 and second['items'][0]['id']=='event-020'
    assert not set(item['id'] for item in first['items']) & set(item['id'] for item in second['items'])
