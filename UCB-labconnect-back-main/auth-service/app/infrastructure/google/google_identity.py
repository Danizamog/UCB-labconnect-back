"""Verificacion de id_token de Google con `google-auth` (firma offline).

Los imports de `google.auth*` son lazy: si la dependencia no esta instalada,
el servicio arranca igual y solo falla cuando alguien intenta usar el SSO,
con un mensaje claro. Asi `/institutional/config` y el resto de los endpoints
siguen respondiendo aunque falte la libreria en el entorno.
"""
from __future__ import annotations


_VALID_ISSUERS = ("accounts.google.com", "https://accounts.google.com")
_MISSING_DEPENDENCY_MESSAGE = (
    "El acceso institucional no esta disponible: falta la dependencia 'google-auth'. "
    "Instala los requirements del auth-service (pip install -r requirements.txt) o "
    "reconstruye la imagen Docker."
)


class GoogleIdentityTokenVerifier:
    def __init__(self, client_id: str) -> None:
        self.client_id = client_id.strip()
        self._request = None
        self._id_token_module = None
        self._auth_error_cls: type[BaseException] = ValueError

    def _ensure_dependencies(self) -> None:
        if self._request is not None and self._id_token_module is not None:
            return
        try:
            from google.auth.exceptions import GoogleAuthError  # type: ignore
            from google.auth.transport import requests as google_auth_requests  # type: ignore
            from google.oauth2 import id_token  # type: ignore
        except ImportError as exc:
            raise ValueError(_MISSING_DEPENDENCY_MESSAGE) from exc

        self._request = google_auth_requests.Request()
        self._id_token_module = id_token
        self._auth_error_cls = GoogleAuthError

    def verify(self, credential: str) -> dict:
        if not self.client_id:
            raise ValueError("El acceso institucional no esta configurado en el servidor")

        normalized_credential = credential.strip()
        if not normalized_credential:
            raise ValueError("No se recibio una credencial valida del proveedor institucional")

        self._ensure_dependencies()

        try:
            payload = self._id_token_module.verify_oauth2_token(
                normalized_credential,
                self._request,
                audience=self.client_id,
            )
        except (self._auth_error_cls, ValueError) as exc:
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
