from dataclasses import dataclass


@dataclass
class Asset:
    id: int
    name: str
    category: str
    description: str | None = None
    serial_number: str | None = None
    laboratory_id: int | None = None
    status: str = "available"
