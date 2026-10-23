from __future__ import annotations

from threading import Lock

from app.core.config import settings
from app.infrastructure.pocketbase_client import PocketBaseClient as AdminPocketBaseClient
from app.schemas.penalty import PenaltyReactivationHistoryRecordCreate, PenaltyReactivationHistoryRecordResponse


def _escape_filter_value(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


class PenaltyReactivationHistoryStore:
    def __init__(self) -> None:
        self._collection = settings.pb_penalty_reactivation_history_collection
        self._admin_client = AdminPocketBaseClient(
            base_url=settings.pocketbase_url,
            auth_identity=settings.pocketbase_auth_identity,
            auth_password=settings.pocketbase_auth_password,
            auth_collection=settings.pocketbase_auth_collection,
            timeout_seconds=settings.pocketbase_timeout_seconds,
        )
        self._collection_ready = False
        self._collection_lock = Lock()

    def _ensure_collection(self) -> None:
        if self._collection_ready or not self._admin_client.enabled:
            return

        with self._collection_lock:
            if self._collection_ready:
                return

            self._admin_client.ensure_collection(
                self._collection,
                [
                    {"name": "penalty_id", "type": "text", "required": True, "max": 120},
                    {"name": "user_id", "type": "text", "required": True, "max": 120},
                    {"name": "user_name", "type": "text", "required": False, "max": 180},
                    {"name": "user_email", "type": "text", "required": False, "max": 180},
                    {"name": "actor_user_id", "type": "text", "required": True, "max": 120},
                    {"name": "actor_name", "type": "text", "required": True, "max": 180},
                    {"name": "executed_at", "type": "date", "required": True},
                    {"name": "lift_reason", "type": "text", "required": False, "max": 3000},
                    {"name": "resolution_notes", "type": "text", "required": False, "max": 4000},
                    {"name": "action_source", "type": "text", "required": True, "max": 80},
                    {"name": "user_was_inactive", "type": "bool", "required": False},
                    {"name": "user_is_active_after", "type": "bool", "required": False},
                    {"name": "privileges_restored", "type": "bool", "required": False},
                    {"name": "active_penalty_count_after", "type": "number", "required": False},
                    {"name": "active_damage_count_at_validation", "type": "number", "required": False},
                    {"name": "regularization_confirmed", "type": "bool", "required": False},
                    {"name": "regularization_summary", "type": "text", "required": False, "max": 3000},
                    {"name": "notification_sent", "type": "bool", "required": False},
                    {"name": "email_sent", "type": "bool", "required": False},
                ],
            )
            self._collection_ready = True

    def _to_response(self, record: dict) -> PenaltyReactivationHistoryRecordResponse:
        return PenaltyReactivationHistoryRecordResponse(
            id=str(record.get("id") or "").strip(),
            penalty_id=str(record.get("penalty_id") or "").strip(),
            user_id=str(record.get("user_id") or "").strip(),
            user_name=str(record.get("user_name") or "").strip(),
            user_email=str(record.get("user_email") or "").strip(),
            actor_user_id=str(record.get("actor_user_id") or "").strip(),
            actor_name=str(record.get("actor_name") or "").strip(),
            executed_at=str(record.get("executed_at") or "").strip(),
            lift_reason=str(record.get("lift_reason") or "").strip(),
            resolution_notes=str(record.get("resolution_notes") or "").strip(),
            action_source=str(record.get("action_source") or "admin_profile").strip() or "admin_profile",
            user_was_inactive=bool(record.get("user_was_inactive", False)),
            user_is_active_after=bool(record.get("user_is_active_after", True)),
            privileges_restored=bool(record.get("privileges_restored", True)),
            active_penalty_count_after=int(record.get("active_penalty_count_after") or 0),
            active_damage_count_at_validation=int(record.get("active_damage_count_at_validation") or 0),
            regularization_confirmed=bool(record.get("regularization_confirmed", False)),
            regularization_summary=str(record.get("regularization_summary") or "").strip(),
            notification_sent=bool(record.get("notification_sent", False)),
            email_sent=bool(record.get("email_sent", False)),
            created=str(record.get("created") or "").strip(),
            updated=str(record.get("updated") or "").strip(),
        )

    def list_for_user(self, user_id: str) -> list[PenaltyReactivationHistoryRecordResponse]:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id or not self._admin_client.enabled:
            return []

        self._ensure_collection()
        records = self._admin_client.list_records(
            self._collection,
            sort="-executed_at",
            filter=f'user_id="{_escape_filter_value(normalized_user_id)}"',
            per_page=100,
        )
        return [self._to_response(record) for record in records]

    def create(self, body: PenaltyReactivationHistoryRecordCreate) -> PenaltyReactivationHistoryRecordResponse:
        if not self._admin_client.enabled:
            return PenaltyReactivationHistoryRecordResponse(
                id="",
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
                created="",
                updated="",
            )

        self._ensure_collection()
        record = self._admin_client.create_record(
            self._collection,
            {
                "penalty_id": body.penalty_id,
                "user_id": body.user_id,
                "user_name": body.user_name,
                "user_email": body.user_email,
                "actor_user_id": body.actor_user_id,
                "actor_name": body.actor_name,
                "executed_at": body.executed_at,
                "lift_reason": body.lift_reason,
                "resolution_notes": body.resolution_notes,
                "action_source": body.action_source,
                "user_was_inactive": body.user_was_inactive,
                "user_is_active_after": body.user_is_active_after,
                "privileges_restored": body.privileges_restored,
                "active_penalty_count_after": body.active_penalty_count_after,
                "active_damage_count_at_validation": body.active_damage_count_at_validation,
                "regularization_confirmed": body.regularization_confirmed,
                "regularization_summary": body.regularization_summary,
                "notification_sent": body.notification_sent,
                "email_sent": body.email_sent,
            },
        )
        return self._to_response(record)
