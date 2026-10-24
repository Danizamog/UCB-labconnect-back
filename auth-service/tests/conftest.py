"""Todas las pruebas de autenticacion usan almacenamiento y secretos de prueba."""
import os

import pytest

os.environ["SECRET_KEY"] = "isolated-test-secret-never-used-in-production"
os.environ["POCKETBASE_URL"] = ""
os.environ["RECAPTCHA_ENABLED"] = "false"


@pytest.fixture(autouse=True)
def isolated_captcha(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "recaptcha_enabled", False)
