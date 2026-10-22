import pytest

from app.domain.password_policy import validate_password


@pytest.mark.parametrize("password", ["Segura2026!x", "Frase-larga-2026"])
def test_accepts_required_password(password: str) -> None:
    validate_password(password)


@pytest.mark.parametrize(
    "password",
    ["Corta1!", "sololetrassimbolo!", "12345678901!", "SoloLetras1234", "Valida2026!\n"],
)
def test_rejects_password_without_all_requirements(password: str) -> None:
    with pytest.raises(ValueError):
        validate_password(password)


@pytest.mark.parametrize("password", ["lowercase2026!", "UPPERCASE2026!"])
def test_requires_uppercase_and_lowercase(password: str) -> None:
    with pytest.raises(ValueError):
        validate_password(password)
