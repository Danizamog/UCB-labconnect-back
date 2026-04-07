from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings
from app.core.datetime_utils import parse_datetime
from app.schemas.penalty import PenaltyResponse

logger = logging.getLogger(__name__)


def _format_localish(value: str) -> str:
    parsed = parse_datetime(value)
    return parsed.strftime("%d/%m/%Y %H:%M")


def _smtp_is_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_sender)


def send_penalty_email(*, penalty: PenaltyResponse) -> bool:
    if not _smtp_is_configured() or not penalty.user_email:
        logger.warning("SMTP no configurado o email del usuario ausente; no se pudo enviar aviso de penalizacion")
        return False

    message = EmailMessage()
    message["Subject"] = "LabConnect - Penalizacion por dano registrada"
    message["From"] = settings.smtp_sender
    message["To"] = penalty.user_email
    message.set_content(
        "\n".join(
            [
                f"Hola {penalty.user_name or penalty.user_id},",
                "",
                "Se ha registrado una penalizacion sobre tu cuenta de laboratorio.",
                f"Motivo: {penalty.reason}",
                f"Inicio: {_format_localish(penalty.starts_at)}",
                f"Fin: {_format_localish(penalty.ends_at)}",
                f"Evidencia: {penalty.evidence_type} #{penalty.evidence_report_id or 'sin ID'}",
                "",
                "Mientras la penalizacion este activa no podras crear nuevas solicitudes de reserva.",
                "",
                "Equipo LabConnect",
            ]
        )
    )

    smtp_client: smtplib.SMTP | smtplib.SMTP_SSL
    try:
        if settings.smtp_use_ssl:
            smtp_client = smtplib.SMTP_SSL(
                settings.smtp_host,
                settings.smtp_port,
                timeout=settings.smtp_timeout_seconds,
            )
        else:
            smtp_client = smtplib.SMTP(
                settings.smtp_host,
                settings.smtp_port,
                timeout=settings.smtp_timeout_seconds,
            )

        with smtp_client as server:
            if settings.smtp_use_tls and not settings.smtp_use_ssl:
                server.starttls()
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)
        return True
    except Exception:
        logger.exception("No se pudo enviar el correo de penalizacion para el usuario %s", penalty.user_id)
        return False
