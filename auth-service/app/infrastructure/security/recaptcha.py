"""Verificacion de reCAPTCHA v2 exclusivamente en el servidor."""
import httpx

from app.core.config import settings

VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"


class RecaptchaRejected(Exception):
    pass


class RecaptchaUnavailable(Exception):
    pass


def is_recaptcha_configured() -> bool:
    return bool(settings.recaptcha_site_key and settings.recaptcha_secret_key and settings.recaptcha_allowed_hostnames)


def verify_recaptcha(token: str | None) -> None:
    if not settings.recaptcha_enabled:
        return
    if not is_recaptcha_configured():
        raise RecaptchaUnavailable()
    if not token or not token.strip():
        raise RecaptchaRejected()
    try:
        with httpx.Client(timeout=5.0, follow_redirects=False) as client:
            response = client.post(VERIFY_URL, data={"secret": settings.recaptcha_secret_key, "response": token})
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, ValueError):
        # No incluir la excepcion HTTP, el secreto o el token en mensajes o logs.
        raise RecaptchaUnavailable() from None
    if not isinstance(result, dict):
        raise RecaptchaUnavailable()
    codes = result.get("error-codes") or []
    if not isinstance(codes, list) or any(not isinstance(code, str) for code in codes):
        raise RecaptchaUnavailable()
    if any(code in codes for code in ("missing-input-secret", "invalid-input-secret")):
        raise RecaptchaUnavailable()
    hostname = result.get("hostname")
    if result.get("success") is not True or not isinstance(hostname, str) or hostname.lower() not in settings.recaptcha_allowed_hostnames:
        raise RecaptchaRejected()
