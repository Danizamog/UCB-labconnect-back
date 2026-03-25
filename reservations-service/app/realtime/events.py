from __future__ import annotations

from datetime import datetime
from typing import Any

from anyio import from_thread

from app.realtime.hub import realtime_hub


def publish_reservations_event(
    event_type: str,
    entity: str,
    payload: dict[str, Any],
) -> None:
    message = {
        "channel": "reservations",
        "event_type": event_type,
        "entity": entity,
        "timestamp": datetime.utcnow().isoformat(),
        "payload": payload,
    }

    try:
        from_thread.run(realtime_hub.broadcast, message)
    except RuntimeError:
        pass
