import pytest
from fastapi import HTTPException

from app.core.dependencies import ensure_any_permission


@pytest.mark.parametrize(
    "current_user",
    [
        {},
        {"role": "Administrador", "permissions": []},
        {"role": "Encargado de Laboratorio"},
        {"permissions": ["permiso_no_relacionado"]},
    ],
)
def test_sensitive_operation_is_denied_without_explicit_permission(current_user) -> None:
    with pytest.raises(HTTPException) as exc:
        ensure_any_permission(current_user, {"gestionar_inventario"}, "Acceso denegado")

    assert exc.value.status_code == 403
    assert exc.value.detail == "Acceso denegado"


def test_explicit_permission_allows_sensitive_operation() -> None:
    ensure_any_permission(
        {"role": "Rol personalizado", "permissions": ["gestionar_inventario"]},
        {"gestionar_inventario"},
        "Acceso denegado",
    )
