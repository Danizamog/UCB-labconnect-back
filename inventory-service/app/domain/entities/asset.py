from dataclasses import dataclass


@dataclass
class Asset:
    id: int
    name: str
    category: str
    description: str | None = None
    serial_number: str | None = None
    laboratory_id: int | None = None
    location: str | None = None
    status: str = "available"
    item_type: str = "equipo"
    brand: str | None = None
    model: str | None = None
    quantity: float | None = None
    unit: str | None = None
    expiry_date: str | None = None
    provider: str | None = None
    concentration: str | None = None
