from __future__ import annotations

from datetime import datetime, UTC
from threading import Lock
from uuid import uuid4

from app.schemas.notification import UserNotificationResponse

# Identificador reservado para notificaciones dirigidas al equipo operativo / sistema
OPERATIONS_RECIPIENT_ID = "__operations__"


class NotificationStore:
    """
    Almacén de notificaciones en memoria (thread-safe).
    Gestiona el ciclo de vida de las notificaciones por usuario y por reserva
    utilizando bloqueos para prevenir condiciones de carrera en entornos concurrentes.
    """

    def __init__(self, max_notifications_per_user: int = 100) -> None:
        """
        Inicializa las estructuras en memoria del almacén:
        - _notifications_by_user: Diccionario donde cada clave es el ID de un usuario
          y su valor es la lista de sus notificaciones en orden cronológico inverso.
        - _users_by_reservation: Diccionario auxiliar (índice secundario) que mapea
          cada reservation_id a un conjunto (set) de IDs de usuarios relacionados.
        - _lock: Cerrojo de exclusión mutua para garantizar concurrencia segura.
        - _max_notifications_per_user: Límite máximo de notificaciones retenidas por usuario.
        """
        self._notifications_by_user: dict[str, list[UserNotificationResponse]] = {}
        self._users_by_reservation: dict[str, set[str]] = {}
        self._lock = Lock()
        self._max_notifications_per_user = max_notifications_per_user

    def create(
        self,
        *,
        recipient_user_id: str,
        notification_type: str,
        title: str,
        message: str,
        payload: dict | None = None,
    ) -> UserNotificationResponse:
        """
        Crea y persiste una nueva notificación en el buzón del usuario destinatario:
        1. Construye la instancia con un UUID único, timestamp actual en UTC e is_read=False.
        2. Adquiere el bloqueo para insertar la notificación al inicio del buzón (más reciente primero).
        3. Si la lista excede el límite máximo permitido, recorta los elementos más antiguos del final.
        4. Si el payload contiene un reservation_id, indexa al usuario dentro de _users_by_reservation.
        """
        # Construcción del modelo de respuesta con identificadores y metadatos iniciales
        notification = UserNotificationResponse(
            id=str(uuid4()),
            recipient_user_id=recipient_user_id,
            notification_type=notification_type,
            title=title,
            message=message,
            payload=payload or {},
            is_read=False,
            created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )

        with self._lock:
            # Obtiene o inicializa la lista de notificaciones para este usuario
            bucket = self._notifications_by_user.setdefault(recipient_user_id, [])
            
            # Inserta al principio para mantener orden descendente por fecha (más nuevo primero)
            bucket.insert(0, notification)
            
            # Aplica la política de retención: descarta notificaciones excedentes del final
            if len(bucket) > self._max_notifications_per_user:
                del bucket[self._max_notifications_per_user :]

            # Actualiza el índice secundario si la notificación está ligada a una reserva
            reservation_id = str((payload or {}).get("reservation_id") or "").strip()
            if reservation_id:
                self._users_by_reservation.setdefault(reservation_id, set()).add(recipient_user_id)

        return notification

    def list_for_user(self, recipient_user_id: str) -> list[UserNotificationResponse]:
        """
        Retorna una copia superficial de la lista de notificaciones de un usuario.
        Al devolver una copia (list(...)), se protege la lista interna de modificaciones externas.
        """
        with self._lock:
            return list(self._notifications_by_user.get(recipient_user_id, []))

    def mark_as_read(
        self,
        *,
        recipient_user_id: str,
        notification_id: str,
    ) -> UserNotificationResponse | None:
        """
        Busca y marca como leída una notificación específica perteneciente a un usuario:
        - Recorre el buzón del usuario buscando coincidencia por notification_id.
        - Si la encuentra, genera una copia actualizada con is_read=True y la reemplaza en la lista.
        - Retorna la notificación actualizada, o None si no se encontró en el buzón del usuario.
        """
        with self._lock:
            bucket = self._notifications_by_user.get(recipient_user_id, [])
            for index, notification in enumerate(bucket):
                if notification.id != notification_id:
                    continue

                # Crea una nueva copia inmutable con el estado modificado
                updated_notification = notification.model_copy(update={"is_read": True})
                bucket[index] = updated_notification
                return updated_notification

        return None

    def mark_as_read_for_any(
        self,
        *,
        recipient_user_ids: list[str],
        notification_id: str,
    ) -> UserNotificationResponse | None:
        """
        Busca una notificación por su ID a través de una lista de posibles usuarios destinatarios.
        Al encontrar la primera coincidencia, la marca como leída (is_read=True),
        la actualiza en el buzón correspondiente y la retorna de inmediato.
        """
        with self._lock:
            for recipient_user_id in recipient_user_ids:
                bucket = self._notifications_by_user.get(recipient_user_id, [])
                for index, notification in enumerate(bucket):
                    if notification.id != notification_id:
                        continue

                    # Actualiza la notificación y detiene la búsqueda entre los demás usuarios
                    updated_notification = notification.model_copy(update={"is_read": True})
                    bucket[index] = updated_notification
                    return updated_notification

        return None

    def mark_all_as_read(self, *, recipient_user_id: str) -> int:
        """
        Marca todas las notificaciones pendientes (is_read=False) de un usuario como leídas.
        Retorna la cantidad total de notificaciones que cambiaron de estado.
        """
        updated_count = 0

        with self._lock:
            bucket = self._notifications_by_user.get(recipient_user_id, [])
            for index, notification in enumerate(bucket):
                if notification.is_read:
                    continue

                bucket[index] = notification.model_copy(update={"is_read": True})
                updated_count += 1

        return updated_count

    def mark_all_as_read_for_many(self, *, recipient_user_ids: list[str]) -> int:
        """
        Marca como leídas todas las notificaciones pendientes para múltiples usuarios en lote.
        Retorna la sumatoria acumulada de notificaciones actualizadas a través de todos los destinatarios.
        """
        updated_count = 0

        with self._lock:
            for recipient_user_id in recipient_user_ids:
                bucket = self._notifications_by_user.get(recipient_user_id, [])
                for index, notification in enumerate(bucket):
                    if notification.is_read:
                        continue

                    bucket[index] = notification.model_copy(update={"is_read": True})
                    updated_count += 1

        return updated_count

    def delete_for_reservation(self, *, reservation_id: str, exclude_types: list[str] | None = None) -> int:
        """
        Elimina en lote las notificaciones asociadas a una reserva específica:
        1. Utiliza _users_by_reservation para acceder directamente a los usuarios afectados sin escanear todo el almacén.
        2. Filtra el buzón de cada usuario conservando las notificaciones que no coincidan con reservation_id
           o cuyo tipo esté en la lista exclude_types (para preservar registros como cancelaciones).
        3. Reemplaza el buzón con la lista filtrada y calcula cuántas fueron removidas.
        4. Mantiene actualizado el índice _users_by_reservation (removiéndolo si ningún usuario conserva notificaciones de esa reserva).
        5. Retorna el total acumulado de notificaciones eliminadas.
        """
        deleted_count = 0
        exclude_types_set = set(exclude_types or [])

        with self._lock:
            # Obtiene los IDs de usuarios que tienen notificaciones para esta reserva
            recipient_ids = list(self._users_by_reservation.get(reservation_id, set()))
            still_has_notif: set[str] = set()

            for recipient_user_id in recipient_ids:
                bucket = self._notifications_by_user.get(recipient_user_id)
                if not bucket:
                    continue

                original_count = len(bucket)
                kept: list[UserNotificationResponse] = []

                for n in bucket:
                    # Determina si la notificación debe ser eliminada
                    is_target = (
                        n.payload
                        and n.payload.get("reservation_id") == reservation_id
                        and n.notification_type not in exclude_types_set
                    )
                    if is_target:
                        continue  # Se omite, por lo tanto se elimina

                    kept.append(n)
                    # Registra si el usuario todavía conserva alguna notificación de esta reserva (por estar excluida)
                    if n.payload and n.payload.get("reservation_id") == reservation_id:
                        still_has_notif.add(recipient_user_id)

                self._notifications_by_user[recipient_user_id] = kept
                deleted_count += original_count - len(kept)

            # Limpia o actualiza el índice secundario de reservas según corresponda
            if still_has_notif:
                self._users_by_reservation[reservation_id] = still_has_notif
            else:
                self._users_by_reservation.pop(reservation_id, None)

        return deleted_count


# Instancia singleton para uso global en la aplicación
notification_store = NotificationStore()
