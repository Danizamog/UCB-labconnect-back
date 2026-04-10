from datetime import UTC, datetime

from app.core.config import settings
from app.infrastructure.pocketbase_base import PocketBaseClient
from app.schemas.penalty import PenaltyCreate, PenaltyResponse

_COLLECTION = settings.pb_user_penalty_collection


def _to_response(record: dict) -> PenaltyResponse:
    """Convert PocketBase record to PenaltyResponse schema"""
    return PenaltyResponse(
        id=record.get("id", ""),
        user_id=record.get("user_id", ""),
        user_name=record.get("user_name", ""),
        user_email=record.get("user_email", ""),
        reason=record.get("reason", ""),
        evidence_type=record.get("evidence_type", "damage_report"),
        evidence_report_id=record.get("evidence_report_id", ""),
        incident_scope=record.get("incident_scope", "laboratory"),
        incident_laboratory_id=record.get("incident_laboratory_id", ""),
        incident_date=record.get("incident_date", ""),
        incident_start_time=record.get("incident_start_time", ""),
        incident_end_time=record.get("incident_end_time", ""),
        asset_id=record.get("asset_id", ""),
        status=_calculate_status(record.get("starts_at", ""), record.get("ends_at", ""), record.get("lifted_at")),
        is_active=_is_active(record.get("starts_at", ""), record.get("ends_at", ""), record.get("lifted_at")),
        created_at=record.get("created", ""),
        created_by=record.get("created_by", ""),
        created_by_name=record.get("created_by_name", ""),
        starts_at=record.get("starts_at", ""),
        ends_at=record.get("ends_at", ""),
        lifted_at=record.get("lifted_at", ""),
        lifted_by=record.get("lifted_by", ""),
        lift_reason=record.get("lift_reason", ""),
        notes=record.get("notes", ""),
        email_sent=bool(record.get("email_sent", False)),
    )


def _parse_iso_datetime(value: str | None) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _calculate_status(starts_at: str, ends_at: str, lifted_at: str | None) -> str:
    """Calculate penalty status: scheduled, active, expired, or lifted"""
    if lifted_at:
        return "lifted"

    start_value = _parse_iso_datetime(starts_at)
    end_value = _parse_iso_datetime(ends_at)
    if start_value is None or end_value is None:
        return "expired"

    now = datetime.now(UTC)
    if start_value > now:
        return "scheduled"
    if end_value <= now:
        return "expired"
    return "active"


def _is_active(starts_at: str, ends_at: str, lifted_at: str | None) -> bool:
    """Check if penalty is currently blocking user"""
    if lifted_at:
        return False

    start_value = _parse_iso_datetime(starts_at)
    end_value = _parse_iso_datetime(ends_at)
    if start_value is None or end_value is None:
        return False

    now = datetime.now(UTC)
    return start_value <= now < end_value


class UserPenaltyRepository:
    """Repository for managing user penalties in PocketBase"""
    
    def __init__(self, client: PocketBaseClient) -> None:
        self._client = client
        self._base = f"/api/collections/{_COLLECTION}/records"

    def create(self, body: PenaltyCreate, created_by: str, created_by_name: str) -> PenaltyResponse:
        """Create a new penalty record"""
        payload = {
            "user_id": body.user_id,
            "user_name": body.user_name,
            "user_email": body.user_email,
            "reason": body.reason,
            "evidence_type": body.evidence_type,
            "evidence_report_id": body.evidence_report_id or "",
            "incident_scope": body.incident_scope or "laboratory",
            "incident_laboratory_id": body.incident_laboratory_id or "",
            "incident_date": body.incident_date or "",
            "incident_start_time": body.incident_start_time or "",
            "incident_end_time": body.incident_end_time or "",
            "asset_id": body.asset_id or "",
            "starts_at": body.starts_at or datetime.utcnow().isoformat(),
            "ends_at": body.ends_at,
            "created_by": created_by,
            "created_by_name": created_by_name,
            "notes": body.notes or "",
            "email_sent": False,
            "lifted_at": "",
            "lifted_by": "",
            "lift_reason": "",
        }
        
        response = self._client.request("POST", self._base, payload=payload)
        
        if not isinstance(response, dict):
            raise ValueError("Failed to create penalty record")
        
        return _to_response(response)

    def list_all(self, page: int = 1, per_page: int = 200) -> list[PenaltyResponse]:
        """List all penalties"""
        items: list[PenaltyResponse] = []
        current_page = page
        
        while True:
            data = self._client.request(
                "GET",
                self._base,
                params={"page": current_page, "perPage": per_page, "sort": "-starts_at"},
            )
            
            if not isinstance(data, dict):
                break
            
            records = data.get("items", [])
            if not isinstance(records, list) or not records:
                break
            
            items.extend(_to_response(r) for r in records if isinstance(r, dict))
            
            total_pages = int(data.get("totalPages", current_page))
            if current_page >= total_pages:
                break
            
            current_page += 1
        
        return items

    def list_for_user(self, user_id: str) -> list[PenaltyResponse]:
        """List all penalties for a specific user"""
        filter_expr = f'user_id="{_escape_filter_value(user_id)}"'
        
        data = self._client.request(
            "GET",
            self._base,
            params={"filter": filter_expr, "sort": "-starts_at", "perPage": 200},
        )
        
        if not isinstance(data, dict):
            return []
        
        records = data.get("items", [])
        return [_to_response(r) for r in records if isinstance(r, dict)]

    def get_active_for_user(self, user_id: str) -> PenaltyResponse | None:
        """Get the currently active penalty for a user (if any)"""
        penalties = self.list_for_user(user_id)
        
        for penalty in penalties:
            if penalty.is_active:
                return penalty
        
        return None

    def get_by_id(self, penalty_id: str) -> PenaltyResponse | None:
        """Get a specific penalty by ID"""
        try:
            response = self._client.request("GET", f"{self._base}/{_escape_filter_value(penalty_id)}")
            
            if not isinstance(response, dict):
                return None
            
            return _to_response(response)
        except Exception:
            return None

    def lift(self, penalty_id: str, lifted_by: str, lift_reason: str) -> PenaltyResponse | None:
        """Lift (remove) an active penalty"""
        penalty = self.get_by_id(penalty_id)
        
        if not penalty:
            return None
        
        payload = {
            "lifted_at": datetime.utcnow().isoformat(),
            "lifted_by": lifted_by,
            "lift_reason": lift_reason or "",
        }
        
        response = self._client.request(
            "PATCH",
            f"{self._base}/{_escape_filter_value(penalty_id)}",
            payload=payload,
        )
        
        if not isinstance(response, dict):
            return None
        
        return _to_response(response)

    def update_email_delivery(self, penalty_id: str, email_sent: bool) -> PenaltyResponse | None:
        """Update email delivery status"""
        payload = {"email_sent": email_sent}
        
        response = self._client.request(
            "PATCH",
            f"{self._base}/{_escape_filter_value(penalty_id)}",
            payload=payload,
        )
        
        if not isinstance(response, dict):
            return None
        
        return _to_response(response)


def _escape_filter_value(value: str) -> str:
    """Escape PocketBase filter values"""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')
