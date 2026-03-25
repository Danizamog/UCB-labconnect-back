from typing import Protocol

from app.domain.entities.asset import Asset


class AssetRepository(Protocol):
    def list_all(self) -> list[Asset]:
        ...

    def create(self, asset: Asset) -> Asset:
        ...

    def get_by_id(self, asset_id: int) -> Asset | None:
        ...

    def update(self, asset: Asset, changed_by: str | None = None, notes: str | None = None) -> Asset:
        ...

    def list_status_logs(self, asset_id: int) -> list[dict]:
        ...

    def delete(self, asset_id: int) -> None:
        ...
