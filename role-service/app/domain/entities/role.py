from dataclasses import dataclass, field


@dataclass
class Role:
    id: int
    name: str
    description: str | None = None
    permissions: list[str] = field(default_factory=list)
    is_active: bool = True
