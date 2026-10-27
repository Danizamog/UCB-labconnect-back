from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta

from app.application.container import lab_reservation_repo
from app.core.config import settings
from app.core.datetime_utils import parse_datetime
from app.notifications.store import notification_store
from app.realtime.manager import realtime_manager
from app.schemas.lab_reservation import LabReservationResponse

# Intervalo en segundos con el que el bucle en segundo plano despierta para verificar reservas
CHECK_INTERVAL_SECONDS = settings.reservation_reminder_check_interval_seconds

# Reglas de recordatorio: (código_identificador, anticipación, título, mensaje)
REMINDER_RULES = (
    ("24h", timedelta(hours=24), "Recordatorio de Reserva", "Tu reserva aprobada comienza en 24 horas."),
    ("30m", timedelta(minutes=30), "Recordatorio Cercano", "Tu reserva aprobada comienza en 30 minutos."),
)

# Ventana máxima de búsqueda en la BD basada en la regla de recordatorio más lejana (24 horas)
MAX_REMINDER_WINDOW = max(delta for _, delta, _, _ in REMINDER_RULES)


class ReservationReminderScheduler:
    """
    Planificador asíncrono en segundo plano para el envío automático de recordatorios
    de reservas de laboratorios próximas a iniciar.
    
    Verifica periódicamente las reservas activas y aprobadas, genera las notificaciones
    correspondientes cuando se cumple la ventana de tiempo y las emite en tiempo real por WebSockets.
    """

    def __init__(self) -> None:
        """
        Inicializa las estructuras de control del scheduler:
        - _task: Referencia a la tarea asíncrona de asyncio en segundo plano.
        - _stop_event: Evento de asyncio para señalizar la detención ordenada del bucle.
        - _sent_reminders: Diccionario de deduplicación en memoria que rastrea los recordatorios
          ya despachados para evitar envíos duplicados ({clave_recordatorio: fecha_inicio_reserva}).
        """
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._sent_reminders: dict[str, datetime] = {}

    def start(self) -> None:
        """
        Inicia el bucle de ejecución periódica en segundo plano si no está corriendo actualmente.
        Limpia el evento de parada y registra la corutina `_run` en el event loop de asyncio.
        """
        if self._task and not self._task.done():
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="reservation-reminder-scheduler")

    async def stop(self) -> None:
        """
        Detiene el bucle de recordatorios de forma segura:
        Señaliza el evento de parada, cancela la tarea asíncrona y espera su terminación
        suprimiendo la excepción CancelledError esperada durante el cierre.
        """
        self._stop_event.set()
        if self._task is None:
            return

        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def run_once(self, now: datetime | None = None) -> None:
        """
        Ejecuta un ciclo único de evaluación ('tick') de forma manual.
        Útil para pruebas unitarias, invocaciones bajo demanda o tareas cron externas.
        """
        await self._tick(now=now or datetime.utcnow())

    async def _run(self) -> None:
        """
        Bucle principal continuo en segundo plano:
        Ejecuta `_tick` en cada iteración y luego duerme de forma cancelable durante
        CHECK_INTERVAL_SECONDS o hasta que se señale `_stop_event`.
        """
        while not self._stop_event.is_set():
            # Suprime cualquier excepción para que un fallo en un tick no rompa el scheduler completo
            with contextlib.suppress(Exception):
                await self._tick(now=datetime.utcnow())
            try:
                # Espera el intervalo configurado o reacciona inmediatamente si se pide detener el scheduler
                await asyncio.wait_for(self._stop_event.wait(), timeout=CHECK_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                # Se agotó el timeout con normalidad, continúa con el siguiente ciclo
                continue

    async def _tick(self, now: datetime) -> None:
        """
        Ejecución de un ciclo de verificación:
        1. Limpia del caché de deduplicación los recordatorios de reservas cuyo inicio ya ocurrió.
        2. Define la ventana temporal [ahora, ahora + MAX_REMINDER_WINDOW].
        3. Consulta en base de datos (vía hilo secundario) las reservas activas y aprobadas en esa ventana.
        4. Itera y procesa individualmente cada reserva candidata.
        """
        self._prune_sent_reminders(now)

        window_start = now.isoformat()
        window_end = (now + MAX_REMINDER_WINDOW).isoformat()
        
        # Ejecuta la consulta sincrónica del repositorio en un hilo worker para no bloquear el event loop
        candidates = await asyncio.to_thread(
            lab_reservation_repo.list_active_approved_with_start_before,
            start_before=window_end,
            start_after=window_start,
        )

        for reservation in candidates:
            await self._process_reservation(reservation, now)

    def _prune_sent_reminders(self, now: datetime) -> None:
        """
        Mantenimiento de memoria (garbage collection manual):
        Elimina las claves de deduplicación de reservas cuya fecha de inicio ya pasó,
        evitando que el diccionario `_sent_reminders` crezca indefinidamente con el tiempo.
        """
        expired_keys = [key for key, start_at in self._sent_reminders.items() if start_at <= now]
        for key in expired_keys:
            self._sent_reminders.pop(key, None)

    async def _process_reservation(self, reservation: LabReservationResponse, now: datetime) -> None:
        """
        Evalúa y procesa las reglas de recordatorio para una reserva individual:
        1. Valida que la reserva esté aprobada, activa y tenga solicitante asignado.
        2. Parsea y verifica que la fecha de inicio no haya ocurrido todavía.
        3. Recorre cada regla (24h, 30m):
           - Comprueba si el recordatorio ya fue despachado previamente.
           - Evalúa si el momento actual ya alcanzó el umbral de disparo (now >= start_at - delta).
           - Crea la notificación persistente mediante `notification_store`.
           - Registra la clave única en `_sent_reminders` para evitar duplicados futuros.
           - Emite el evento a través de WebSockets (`realtime_manager`) al solicitante de la reserva.
        """
        if reservation.status != "approved" or not reservation.is_active or not reservation.requested_by:
            return

        try:
            start_at = parse_datetime(reservation.start_at)
        except ValueError:
            return

        if start_at <= now:
            return

        for reminder_code, delta, title, message in REMINDER_RULES:
            reminder_at = start_at - delta
            # Clave única de deduplicación compuesta por ID, regla y hora de inicio de la reserva
            reminder_key = f"{reservation.id}:{reminder_code}:{reservation.start_at}"

            # Si ya se envió anteriormente este recordatorio específico, se omite
            if reminder_key in self._sent_reminders:
                continue

            # Si aún no es hora de emitir este recordatorio, se salta
            if now < reminder_at:
                continue

            # Persiste la notificación en el store (en un hilo worker para evitar bloqueos)
            notification = await asyncio.to_thread(
                notification_store.create,
                recipient_user_id=reservation.requested_by,
                notification_type="reservation_reminder",
                title=title,
                message=message,
                payload={
                    "reservation_id": reservation.id,
                    "purpose": reservation.purpose,
                    "starts_at": reservation.start_at,
                    "laboratory_id": reservation.laboratory_id,
                    "status": reservation.status,
                    "reminder_kind": reminder_code,
                },
            )

            # Marca el recordatorio como enviado en memoria junto a su fecha de inicio
            self._sent_reminders[reminder_key] = start_at

            # Notificación push en tiempo real hacia los sockets conectados del usuario solicitante
            await realtime_manager.broadcast(
                {
                    "topic": "user_notification",
                    "action": "create",
                    "recipients": [reservation.requested_by],
                    "record": notification.model_dump(),
                    "at": datetime.utcnow().isoformat(),
                }
            )


# Instancia singleton para gestionar el planificador a nivel de ciclo de vida de la aplicación
reservation_reminder_scheduler = ReservationReminderScheduler()