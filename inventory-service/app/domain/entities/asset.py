from dataclasses import dataclass
from datetime import datetime


@dataclass
class Asset:
    id: int
    name: str
    category: str
    location: str
    description: str | None = None
    serial_number: str | None = None
    laboratory_id: int | None = None
    status: str = "available"
    status_updated_at: datetime | None = None
    status_updated_by: str | None = None
