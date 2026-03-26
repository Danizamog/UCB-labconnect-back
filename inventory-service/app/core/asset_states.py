from enum import Enum


class AssetStatus(str, Enum):
    """Estados válidos para un equipo en el inventario"""
    AVAILABLE = "available"
    LOANED = "loaned"
    MAINTENANCE = "maintenance"
    DAMAGED = "damaged"

    @classmethod
    def is_valid(cls, status: str) -> bool:
        """Valida si un estado es permitido"""
        return status in {s.value for s in cls}

    @classmethod
    def get_all_values(cls) -> set:
        """Retorna todos los valores de estados permitidos"""
        return {s.value for s in cls}
