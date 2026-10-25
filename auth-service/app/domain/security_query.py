"""Consultas de evidencia con filtros antes de paginar y un corte temporal fijo."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import unicodedata

COLLECTION_FIELDS = {
    "security_audit_event": ("actor_email", "actor_id", "action", "reason", "target_id"),
    "auth_session": ("email", "user_id", "reason"),
    "security_incident": ("title", "description", "responsible", "severity"),
    "access_review": ("user_id", "reviewer_id", "role_name", "period", "observation"),
}
ACTION_LABELS = {
    "auth.login.succeeded": "Ingreso con contraseña", "auth.login.failed": "Intento de ingreso fallido correo contraseña incorrectos",
    "auth.sso_login.succeeded": "Ingreso con Google", "auth.sso_login.blocked": "Acceso con Google bloqueado",
    "auth.account.locked": "Cuenta bloqueada por intentos fallidos", "auth.account.unlocked": "Cuenta desbloqueada",
    "auth.password.changed": "Contraseña actualizada", "auth.password.reset": "Contraseña reiniciada por un administrador",
    "auth.session.revoked": "Sesión cerrada", "user.deactivated": "Cuenta dada de baja",
    "auth.captcha.failed": "Verificación CAPTCHA rechazada", "auth.captcha.unavailable": "Verificación CAPTCHA no disponible",
}
BLOCKED_ACTIONS = {"auth.account.locked", "auth.sso_login.blocked"}
SUCCESS = {"success", "succeeded", "ok"}
FAILED = {"failed", "failure", "error", "denied"}
REVOKED = {"revoked", "revocada", "cerrada", "closed"}
CLOSED = {"closed", "resolved", "cerrado", "resuelto"}
REVIEW = {"in_progress", "investigating", "en_progreso"}


def utc_date(value):
    if not value:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def normalized(value):
    return ''.join(char for char in unicodedata.normalize('NFD', str(value or '').lower()) if unicodedata.category(char) != 'Mn')


@dataclass
class SecurityQuery:
    page: int = 1
    per_page: int = 20
    query: str = ""
    status: str = ""
    date_from: date | None = None
    date_to: date | None = None
    snapshot_at: datetime | None = None
    since: datetime | None = None
    auth_only: bool = False

    def __post_init__(self):
        self.snapshot_at = utc_date(self.snapshot_at) or datetime.now(timezone.utc)
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("La fecha inicial debe ser anterior a la final")
        if self.date_to == date.max:
            raise ValueError("La fecha final esta fuera del rango admitido")

    def bounds(self):
        zone = timezone(timedelta(hours=-4))
        start = datetime.combine(self.date_from, time.min, zone).astimezone(timezone.utc) if self.date_from else self.since
        end = datetime.combine(self.date_to + timedelta(days=1), time.min, zone).astimezone(timezone.utc) if self.date_to else None
        return start, end

    @staticmethod
    def state(record, collection, as_of):
        status = str(record.get("status") or "").lower()
        if collection == "security_audit_event":
            if record.get("action") in BLOCKED_ACTIONS:
                return "blocked"
            result = str(record.get("result") or "").lower()
            return "success" if result in SUCCESS else "failed" if result in FAILED else "recorded"
        if collection == "auth_session":
            expiry = utc_date(record.get("expires_at"))
            if status in REVOKED:
                return "revoked"
            if status == "expired" or (expiry and expiry <= as_of):
                return "expired"
            return "active" if status in {"active", "vigente"} and expiry and expiry > as_of else "unknown"
        if collection == "security_incident":
            return "closed" if status in CLOSED else "review" if status in REVIEW else "open"
        return str(record.get("decision") or "unknown")

    def matches(self, record, collection):
        created = utc_date(record.get("created"))
        if not created or created > self.snapshot_at:
            return False
        start, end = self.bounds()
        if (start and created < start) or (end and created >= end):
            return False
        if self.auth_only and not str(record.get("action") or "").startswith("auth."):
            return False
        state = self.state(record, collection, self.snapshot_at)
        if self.status and not (self.status == "unsuccessful" and state in {"failed", "blocked"}) and not (self.status == "unresolved" and collection == "security_incident" and state != "closed") and state != self.status:
            return False
        text = ' '.join(str(record.get(key) or '') for key in COLLECTION_FIELDS[collection])
        text += ' ' + ACTION_LABELS.get(record.get("action"), '')
        return normalized(self.query.strip()) in normalized(text)

    def pocketbase_filter(self, collection):
        fields = COLLECTION_FIELDS[collection]
        def quoted(value):
            return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'
        def any_of(field, values):
            return '(' + ' || '.join(f'{field}={quoted(value)}' for value in sorted(values)) + ')'
        def none_of(field, values):
            return '(' + ' && '.join(f'{field}!={quoted(value)}' for value in sorted(values)) + ')'
        def stamp(value):
            return value.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] + 'Z'
        snapshot = stamp(self.snapshot_at)
        filters = [f'created<={quoted(snapshot)}']
        start, end = self.bounds()
        if start:
            filters.append(f'created>={quoted(stamp(start))}')
        if end:
            filters.append(f'created<{quoted(stamp(end))}')
        if self.auth_only:
            filters.append('action~"auth.%"')
        if self.query.strip():
            search = [f'{field}~{quoted(self.query.strip())}' for field in fields]
            if collection == "security_audit_event":
                actions = {key for key, label in ACTION_LABELS.items() if normalized(self.query.strip()) in normalized(label)}
                if actions:
                    search.append(any_of('action', actions))
            filters.append('(' + ' || '.join(search) + ')')
        status = self.status
        if status:
            if collection == "security_audit_event":
                blocked = any_of('action', BLOCKED_ACTIONS)
                not_blocked = none_of('action', BLOCKED_ACTIONS)
                failed = f'({any_of("result", FAILED)} && {not_blocked})'
                expressions = {"success": f'({any_of("result", SUCCESS)} && {not_blocked})', "failed": failed, "blocked": blocked,
                               "unsuccessful": f'({any_of("result", FAILED)} || {blocked})',
                               "recorded": f'({none_of("result", SUCCESS | FAILED)} && {not_blocked})'}
            elif collection == "auth_session":
                revoked = any_of('status', REVOKED)
                not_revoked = none_of('status', REVOKED)
                expired = f'({not_revoked} && (status="expired" || (expires_at!="" && expires_at<={quoted(snapshot)})))'
                active = f'({any_of("status", {"active", "vigente"})} && expires_at>{quoted(snapshot)})'
                unknown = f'({not_revoked} && status!="expired" && (expires_at="" || expires_at>{quoted(snapshot)}) && ({none_of("status", {"active", "vigente"})} || expires_at=""))'
                expressions = {"active": active, "expired": expired, "revoked": revoked, "unknown": unknown}
            elif collection == "security_incident":
                closed, review = any_of('status', CLOSED), any_of('status', REVIEW)
                expressions = {"closed": closed, "review": review, "open": none_of('status', CLOSED | REVIEW), "unresolved": none_of('status', CLOSED)}
            else:
                expressions = {value: f'decision={quoted(value)}' for value in ('pending', 'approved', 'maintain', 'revoke', 'revoked', 'rejected', 'reviewed')}
            if status not in expressions:
                raise ValueError("Estado de seguridad no valido")
            filters.append(expressions[status])
        return ' && '.join(filters)

    def envelope(self, items, total):
        return {"items": items, "page": self.page, "perPage": self.per_page, "totalItems": total,
                "totalPages": (total + self.per_page - 1) // self.per_page, "snapshotAt": self.snapshot_at.isoformat()}
