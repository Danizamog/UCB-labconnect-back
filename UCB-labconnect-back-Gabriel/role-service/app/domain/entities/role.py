from dataclasses import dataclass, field


@dataclass
class Role:
    id: str
    nombre: str
    descripcion: str | None = None
    permisos: list[str] = field(default_factory=list)
