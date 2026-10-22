import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def is_password_reset_email_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_sender)


def send_password_reset_email(*, recipient: str, name: str | None, token: str) -> bool:
    if not is_password_reset_email_configured():
        logger.error("SMTP no esta configurado para enviar restablecimientos de contrasena")
        return False

    reset_url = f"{settings.frontend_url}/reset-password?token={token}"
    message = EmailMessage()
    message["Subject"] = "LabConnect - Restablece tu contrasena"
    message["From"] = settings.smtp_sender
    message["To"] = recipient
    message.set_content(
        "\n".join(
            [
                f"Hola {name or recipient},",
                "",
                "Recibimos una solicitud para restablecer la contrasena de tu cuenta de LabConnect.",
                "Abre el siguiente enlace para elegir una nueva contrasena:",
                reset_url,
                "",
                "El enlace vence en 30 minutos y solo puede utilizarse una vez.",
                "Si no solicitaste este cambio, puedes ignorar este mensaje.",
                "",
                "Equipo LabConnect",
            ]
        )
    )

    try:
        smtp_client: smtplib.SMTP | smtplib.SMTP_SSL
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
    except (OSError, smtplib.SMTPException):
        logger.exception("No se pudo enviar un restablecimiento de contrasena")
        return False
