from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token


_VALID_ISSUERS = ("accounts.google.com", "https://accounts.google.com")


class GoogleIdentityTokenVerifier:
    def __init__(self, client_id: str) -> None:
        self.client_id = client_id.strip()
        self._request = google_auth_requests.Request()

    def verify(self, credential: str) -> dict:
        if not self.client_id:
            raise ValueError("El acceso institucional no esta configurado en el servidor")

        normalized_credential = credential.strip()
        if not normalized_credential:
            raise ValueError("No se recibio una credencial valida del proveedor institucional")

        try:
            payload = id_token.verify_oauth2_token(
                normalized_credential,
                self._request,
                audience=self.client_id,
            )
        except (GoogleAuthError, ValueError) as exc:
            raise ValueError("No se pudo validar la cuenta institucional") from exc

        if payload.get("iss") not in _VALID_ISSUERS:
            raise ValueError("El proveedor institucional devolvio un emisor invalido")

        if not payload.get("email_verified"):
            raise ValueError("La cuenta institucional no tiene el correo verificado")

        email = str(payload.get("email", "")).strip().lower()
        if not email:
            raise ValueError("El proveedor institucional no devolvio un correo valido")

        return {
            "email": email,
            "name": str(payload.get("name", "")).strip() or email.split("@")[0],
            "picture": payload.get("picture"),
            "google_sub": payload.get("sub"),
        }
