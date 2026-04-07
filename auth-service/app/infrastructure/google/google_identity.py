import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


class GoogleIdentityTokenVerifier:
    tokeninfo_endpoint = "https://oauth2.googleapis.com/tokeninfo"

    def __init__(self, client_id: str) -> None:
        self.client_id = client_id.strip()

    def verify(self, credential: str) -> dict:
        if not self.client_id:
            raise ValueError("El acceso institucional no esta configurado en el servidor")

        normalized_credential = credential.strip()
        if not normalized_credential:
            raise ValueError("No se recibio una credencial valida del proveedor institucional")

        query = urlencode({"id_token": normalized_credential})
        request_url = f"{self.tokeninfo_endpoint}?{query}"

        try:
            with urlopen(request_url, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as exc:
            raise ValueError("No se pudo validar la cuenta institucional") from exc

        if payload.get("aud") != self.client_id:
            raise ValueError("La cuenta institucional no corresponde a esta aplicacion")

        issuer = payload.get("iss")
        if issuer not in {"accounts.google.com", "https://accounts.google.com"}:
            raise ValueError("El proveedor institucional devolvio un emisor invalido")

        if str(payload.get("email_verified")).lower() != "true":
            raise ValueError("La cuenta institucional no tiene el correo verificado")

        try:
            expires_at = int(payload.get("exp", "0"))
        except (TypeError, ValueError) as exc:
            raise ValueError("La respuesta del proveedor institucional no incluye expiracion valida") from exc

        if expires_at <= int(time.time()):
            raise ValueError("La sesion institucional ya expiro")

        email = str(payload.get("email", "")).strip().lower()
        if not email:
            raise ValueError("El proveedor institucional no devolvio un correo valido")

        return {
            "email": email,
            "name": str(payload.get("name", "")).strip() or email.split("@")[0],
            "picture": payload.get("picture"),
            "google_sub": payload.get("sub"),
        }
