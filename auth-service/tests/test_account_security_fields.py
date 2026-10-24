from datetime import datetime, timedelta, timezone

import pytest

from app.domain.account_security import password_change_required
from app.domain.entities.user import User
from app.infrastructure.repositories.pocketbase_user_repository import PocketBaseUserRepository


@pytest.mark.parametrize("provider", ["local", "google", "hybrid"])
def test_pocketbase_security_fields_survive_payload_and_record_mapping(provider, monkeypatch):
    repo = PocketBaseUserRepository("https://unused.invalid")
    fields = {"auth_provider", "google_sub", "session_version", "password_changed_at", "password_expires_at", "must_change_password"}
    monkeypatch.setattr(repo, "_load_supported_fields", lambda: fields)
    changed = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
    user = User(username="field.test@ucb.edu.bo", auth_provider=provider,
                google_sub="bound-identity" if provider != "local" else None,
                session_version=13, password_changed_at=changed.isoformat(),
                password_expires_at=(changed + timedelta(days=90)).isoformat(),
                must_change_password=provider == "google")
    try:
        payload = repo._build_payload(user)
        restored = repo._to_user(payload)
        for name in fields:
            assert getattr(restored, name) == getattr(user, name)
        assert "password" not in payload
    finally:
        repo._client.close()


@pytest.mark.parametrize("expiry,required", [
    ((datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S.000Z"), False),
    ((datetime.now(timezone.utc) - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S.000Z"), True),
    ("invalid-date", True),
])
def test_password_expiry_accepts_pocketbase_dates_and_requires_change_when_invalid(expiry, required):
    assert password_change_required(User(username="expiry@ucb.edu.bo", auth_provider="hybrid", password_expires_at=expiry)) is required
