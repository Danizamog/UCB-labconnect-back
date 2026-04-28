from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from app.api.v1.endpoints import penalties as penalty_endpoints
from app.schemas.penalty import (
    PenaltyReactivationHistoryRecordCreate,
    PenaltyReactivationHistoryRecordResponse,
    PenaltyReactivationRequest,
    PenaltyResponse,
)


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(b"authorization", b"Bearer test-token")],
        }
    )


def _penalty(*, penalty_id: str = "pen-1", is_active: bool = True) -> PenaltyResponse:
    now = datetime.utcnow()
    starts_at = (now - timedelta(days=2)).isoformat()
    ends_at = (now + timedelta(days=2)).isoformat()
    return PenaltyResponse(
        id=penalty_id,
        user_id="user-1",
        user_name="Student One",
        user_email="student1@ucb.edu.bo",
        reason="Dano reportado sobre equipo",
        evidence_type="damage_report",
        evidence_report_id="rep-1",
        asset_id="asset-1",
        related_reservation_id="res-1",
        starts_at=starts_at,
        ends_at=ends_at,
        notes="",
        status="active" if is_active else "lifted",
        is_active=is_active,
        email_sent=False,
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
        created_by="admin-1",
        created_by_name="Admin User",
        lifted_at="",
        lifted_by="",
        lifted_by_name="",
        lift_reason="",
    )


class _FakePenaltyRepo:
    def __init__(self, items: list[PenaltyResponse]) -> None:
        self._items = items
        self.lift_calls: list[tuple[str, str]] = []

    def list_for_user(self, user_id: str) -> list[PenaltyResponse]:
        return [item for item in self._items if item.user_id == user_id]

    def get_by_id(self, penalty_id: str) -> PenaltyResponse | None:
        for item in self._items:
            if item.id == penalty_id:
                return item
        return None

    def lift(self, penalty_id: str, *, current_user: dict, lift_reason: str = "") -> PenaltyResponse | None:
        for index, item in enumerate(self._items):
            if item.id != penalty_id:
                continue

            updated = item.model_copy(
                update={
                    "status": "lifted",
                    "is_active": False,
                    "lifted_at": datetime.utcnow().isoformat(),
                    "lifted_by": str(current_user.get("user_id") or ""),
                    "lifted_by_name": str(current_user.get("name") or ""),
                    "lift_reason": lift_reason,
                }
            )
            self._items[index] = updated
            self.lift_calls.append((penalty_id, lift_reason))
            return updated

        return None


class _FakeHistoryStore:
    def __init__(self) -> None:
        self.created: list[PenaltyReactivationHistoryRecordResponse] = []

    def list_for_user(self, user_id: str) -> list[PenaltyReactivationHistoryRecordResponse]:
        return [item for item in self.created if item.user_id == user_id]

    def create(self, body: PenaltyReactivationHistoryRecordCreate) -> PenaltyReactivationHistoryRecordResponse:
        record = PenaltyReactivationHistoryRecordResponse(
            id=f"hist-{len(self.created) + 1}",
            penalty_id=body.penalty_id,
            user_id=body.user_id,
            user_name=body.user_name,
            user_email=body.user_email,
            actor_user_id=body.actor_user_id,
            actor_name=body.actor_name,
            executed_at=body.executed_at,
            lift_reason=body.lift_reason,
            resolution_notes=body.resolution_notes,
            action_source=body.action_source,
            user_was_inactive=body.user_was_inactive,
            user_is_active_after=body.user_is_active_after,
            privileges_restored=body.privileges_restored,
            active_penalty_count_after=body.active_penalty_count_after,
            active_damage_count_at_validation=body.active_damage_count_at_validation,
            regularization_confirmed=body.regularization_confirmed,
            regularization_summary=body.regularization_summary,
            notification_sent=body.notification_sent,
            email_sent=body.email_sent,
            created=body.executed_at,
            updated=body.executed_at,
        )
        self.created.append(record)
        return record


class PenaltyReactivationTests(unittest.IsolatedAsyncioTestCase):
    async def test_context_marks_user_as_ready_when_regularized(self) -> None:
        repo = _FakePenaltyRepo([_penalty()])
        history = _FakeHistoryStore()
        current_user = {"user_id": "admin-1", "permissions": ["reactivar_cuentas"], "role": "staff", "name": "Admin User"}

        async def _fake_profile(*args, **kwargs):
            return {
                "id": "user-1",
                "name": "Student One",
                "username": "student1@ucb.edu.bo",
                "is_active": True,
            }

        async def _fake_flag(*args, **kwargs):
            return None

        with patch.object(penalty_endpoints, "user_penalty_repo", repo), \
             patch.object(penalty_endpoints, "penalty_reactivation_history_store", history), \
             patch.object(penalty_endpoints, "_fetch_user_profile", _fake_profile), \
             patch.object(penalty_endpoints, "_fetch_user_flag", _fake_flag):
            context = await penalty_endpoints.get_reactivation_context("user-1", request=_request(), current_user=current_user)

        self.assertEqual(context.block_status, "blocked")
        self.assertTrue(context.can_reactivate)
        self.assertTrue(context.privileges_restored_if_confirmed)
        self.assertEqual(context.active_penalty.id, "pen-1")
        self.assertTrue(context.regularization.is_regularized)

    async def test_reactivate_user_account_lifts_penalty_reactivates_user_and_writes_history(self) -> None:
        repo = _FakePenaltyRepo([_penalty()])
        history = _FakeHistoryStore()
        current_user = {"user_id": "admin-1", "permissions": ["reactivar_cuentas"], "role": "staff", "name": "Admin User"}
        activation_updates: list[tuple[str, bool]] = []
        notifications: list[str] = []
        broadcasts: list[str] = []

        async def _fake_profile(*args, **kwargs):
            return {
                "id": "user-1",
                "name": "Student One",
                "username": "student1@ucb.edu.bo",
                "is_active": False,
            }

        async def _fake_flag(*args, **kwargs):
            return None

        async def _fake_activate(user_id: str, *args, **kwargs):
            activation_updates.append((user_id, kwargs.get("is_active")))
            return {"id": user_id, "is_active": True}

        async def _fake_notify(penalty):
            notifications.append(penalty.id)

        async def _fake_broadcast(action: str, penalty):
            broadcasts.append(f"{action}:{penalty.id}")

        with patch.object(penalty_endpoints, "user_penalty_repo", repo), \
             patch.object(penalty_endpoints, "penalty_reactivation_history_store", history), \
             patch.object(penalty_endpoints, "_fetch_user_profile", _fake_profile), \
             patch.object(penalty_endpoints, "_fetch_user_flag", _fake_flag), \
             patch.object(penalty_endpoints, "_set_user_active", _fake_activate), \
             patch.object(penalty_endpoints, "_notify_penalty_lifted", _fake_notify), \
             patch.object(penalty_endpoints, "_broadcast_penalty_event", _fake_broadcast), \
             patch.object(penalty_endpoints, "send_penalty_reactivation_email", lambda **kwargs: True):
            response = await penalty_endpoints.reactivate_user_account(
                "pen-1",
                body=PenaltyReactivationRequest(
                    lift_reason="Cuenta regularizada",
                    resolution_notes="Se verifico cierre del incidente y restitucion del equipo.",
                ),
                request=_request(),
                current_user=current_user,
            )

        self.assertTrue(response.privileges_restored)
        self.assertTrue(response.active_block_removed)
        self.assertEqual(response.user_status, "active")
        self.assertEqual(repo.lift_calls, [("pen-1", "Cuenta regularizada")])
        self.assertEqual(activation_updates, [("user-1", True)])
        self.assertEqual(notifications, ["pen-1"])
        self.assertEqual(broadcasts, ["lift:pen-1"])
        self.assertEqual(len(history.created), 1)
        self.assertTrue(history.created[0].user_was_inactive)
        self.assertTrue(history.created[0].privileges_restored)
        self.assertEqual(history.created[0].resolution_notes, "Se verifico cierre del incidente y restitucion del equipo.")

    async def test_reactivation_is_rejected_when_user_still_has_open_damage_flags(self) -> None:
        repo = _FakePenaltyRepo([_penalty()])
        history = _FakeHistoryStore()
        current_user = {"user_id": "admin-1", "permissions": ["reactivar_cuentas"], "role": "staff", "name": "Admin User"}

        async def _fake_profile(*args, **kwargs):
            return {
                "id": "user-1",
                "name": "Student One",
                "username": "student1@ucb.edu.bo",
                "is_active": True,
            }

        async def _fake_flag(*args, **kwargs):
            return {
                "borrower_email": "student1@ucb.edu.bo",
                "active_damage_count": 2,
                "latest_asset_name": "Osciloscopio Tektronix",
                "latest_ticket_id": "tick-77",
            }

        with patch.object(penalty_endpoints, "user_penalty_repo", repo), \
             patch.object(penalty_endpoints, "penalty_reactivation_history_store", history), \
             patch.object(penalty_endpoints, "_fetch_user_profile", _fake_profile), \
             patch.object(penalty_endpoints, "_fetch_user_flag", _fake_flag):
            with self.assertRaises(HTTPException) as captured:
                await penalty_endpoints.reactivate_user_account(
                    "pen-1",
                    body=PenaltyReactivationRequest(lift_reason="Cuenta regularizada"),
                    request=_request(),
                    current_user=current_user,
                )

        self.assertEqual(captured.exception.status_code, 409)
        self.assertIn("incidente", str(captured.exception.detail).lower())
        self.assertEqual(repo.lift_calls, [])
        self.assertEqual(history.created, [])


if __name__ == "__main__":
    unittest.main()
