from types import SimpleNamespace

import pytest

from app.application.use_cases.manage_roles import ManageRolesUseCase
from app.domain.permission_catalog import DEFAULT_ROLE_TEMPLATES


class FakeRepository:
    def __init__(self, target_role="Estudiante"):
        self.target_role = target_role
        self.updated_role = None

    def list_users_with_roles(self):
        return [{"id": "user-1", "email": "user@ucb.edu.bo", "role": {"nombre": self.target_role}}]

    def get_by_id(self, role_id):
        return SimpleNamespace(nombre=role_id)

    def assign_user_role(self, user_id, role_id):
        return {"id": user_id, "roleId": role_id}

    def get_by_nombre(self, name):
        return SimpleNamespace(nombre="Administrador", descripcion="Anterior", permisos=["asignar_roles"]) if name == "Administrador" else None

    def create(self, role):
        return role

    def update(self, role):
        self.updated_role = role
        return role


def test_access_admin_cannot_assign_privileged_role():
    use_case = ManageRolesUseCase(FakeRepository())
    with pytest.raises(ValueError, match="asignacion privilegiada"):
        use_case.assign_user_role("user-1", "Administrador", actor_email="access@ucb.edu.bo")


def test_access_admin_cannot_demote_privileged_account():
    use_case = ManageRolesUseCase(FakeRepository(target_role="Administrador"))
    with pytest.raises(ValueError, match="roles privilegiados"):
        use_case.assign_user_role("user-1", "Estudiante", actor_email="access@ucb.edu.bo")


def test_access_admin_cannot_change_own_role():
    use_case = ManageRolesUseCase(FakeRepository())
    with pytest.raises(ValueError, match="propio rol"):
        use_case.assign_user_role("user-1", "Docente", actor_email="user@ucb.edu.bo")


def test_access_admin_can_assign_ordinary_role():
    use_case = ManageRolesUseCase(FakeRepository())
    assert use_case.assign_user_role("user-1", "Docente", actor_email="access@ucb.edu.bo")["roleId"] == "Docente"


def test_custom_role_cannot_receive_privileged_permissions():
    use_case = ManageRolesUseCase(FakeRepository())
    with pytest.raises(ValueError, match="permisos privilegiados"):
        use_case.create_role("Rol peligroso", "", ["asignar_roles"], actor_permissions=["asignar_roles"])


def test_custom_operational_role_can_be_created():
    use_case = ManageRolesUseCase(FakeRepository())
    role = use_case.create_role("Operador", "", ["gestionar_reservas"], actor_permissions=[])
    assert role.permisos == ["gestionar_reservas"]


def test_different_admin_can_bootstrap_first_access_admin():
    repository = FakeRepository(target_role="Administrador")
    use_case = ManageRolesUseCase(repository)
    result = use_case.assign_user_role(
        "user-1",
        "Administrador de Accesos",
        actor_email="other.admin@ucb.edu.bo",
        actor_role="Administrador",
    )
    assert result["roleId"] == "Administrador de Accesos"
    assert repository.updated_role is not None
    assert "asignar_roles" not in repository.updated_role.permisos


def test_default_matrix_separates_teaching_approval_and_osi():
    roles = {role["nombre"]: set(role["permisos"]) for role in DEFAULT_ROLE_TEMPLATES}
    assert {"aprobar_clases", "aprobar_tutorias"} <= roles["Administrador"]
    assert not roles["Administrador"].intersection({"gestionar_clases_propias", "solicitar_recursos_clase", "gestionar_tutorias_propias", "gestionar_asistencia_tutorias", "gestionar_observaciones_tutorias", "consultar_auditoria_seguridad", "revisar_accesos_rbac"})
    assert "gestionar_clases_propias" in roles["Docente"]
    assert all("aprobar_clases" not in permissions for name, permissions in roles.items() if name != "Administrador")
