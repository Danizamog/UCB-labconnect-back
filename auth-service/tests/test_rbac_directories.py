import pytest
from fastapi.testclient import TestClient
from app.domain.entities.user import User
from app.infrastructure.repositories.in_memory_user_repository import InMemoryUserRepository
from app.interfaces.http import router
from app.main import app


@pytest.fixture
def directory(monkeypatch):
    repo = InMemoryUserRepository()
    repo.save(User(id='person-1', username='person@ucb.edu.bo', name='Persona', role='Docente',
                   phone='private-phone', bio='private-bio', security_locked=True))
    monkeypatch.setattr(router, 'user_repository', repo)
    actor = {'user_id': 'operator', 'role': 'Rol personalizado', 'permissions': []}
    app.dependency_overrides[router._get_current_payload] = lambda: actor
    yield TestClient(app), actor
    app.dependency_overrides.clear()


@pytest.mark.parametrize('purpose,permission', [
    ('laboratories','gestionar_estructura_laboratorios'), ('schedules','gestionar_horarios_laboratorio'),
    ('loans','gestionar_prestamos'), ('reservations','gestionar_reservas'),
    ('reservations','gestionar_accesos_laboratorio'), ('materials','gestionar_stock'),
    ('materials','gestionar_reactivos_quimicos'), ('materials','gestionar_reservas_materiales'),
    ('penalties','gestionar_penalizaciones'), ('directory','consultar_directorio_operativo'),
])
def test_single_operational_permission_has_minimal_directory_only(directory, purpose, permission):
    client, actor = directory
    actor['permissions'] = [permission]
    response = client.get('/v1/users/operational-directory', params={'purpose':purpose})
    assert response.status_code == 200, response.text
    assert set(response.json()[0]) == {'id','username','name','role','is_active','student_code'}
    assert client.get('/v1/users/').status_code == 403
    assert client.get('/v1/users/person-1').status_code == 403


@pytest.mark.parametrize('permission', ['consultar_usuarios','modificar_usuarios','dar_baja_usuarios','desbloquear_usuarios','reiniciar_credenciales'])
def test_each_account_permission_can_load_its_own_workspace(directory, permission):
    client, actor = directory
    actor['permissions'] = [permission]
    assert client.get('/v1/users/').status_code == 200


def test_role_name_and_unrelated_permission_do_not_grant_directory_access(directory):
    client, actor = directory
    actor.update(role='Administrador', permissions=['aprobar_clases'])
    assert client.get('/v1/users/operational-directory?purpose=laboratories').status_code == 403
    assert client.get('/v1/users/').status_code == 403
    assert client.get('/v1/users/operational-directory?purpose=unknown').status_code == 400


def test_operational_directory_supports_complete_pagination(directory):
    client, actor = directory
    actor['permissions'] = ['gestionar_estructura_laboratorios']
    first = client.get('/v1/users/operational-directory?purpose=laboratories&per_page=1&page=1')
    second = client.get('/v1/users/operational-directory?purpose=laboratories&per_page=1&page=2')
    assert len(first.json()) == 1
    assert second.json() == []
