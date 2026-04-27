from __future__ import annotations


class ConflictError(ValueError):
    """Raised when an operation fails due to a business conflict (overlap, capacity)."""

    pass
