from app.domain.entities.asset import Asset


class InMemoryAssetRepository:
    def __init__(self) -> None:
        self._items: dict[int, Asset] = {}
        self._id_counter = 1

    def list_all(self) -> list[Asset]:
        return sorted(self._items.values(), key=lambda item: item.id, reverse=True)

    def create(self, asset: Asset) -> Asset:
        asset.id = self._id_counter
        self._items[self._id_counter] = asset
        self._id_counter += 1
        return asset

    def get_by_id(self, asset_id: int) -> Asset | None:
        return self._items.get(asset_id)

    def update(self, asset: Asset, changed_by: str | None = None, notes: str | None = None) -> Asset:
        self._items[asset.id] = asset
        return asset

    def list_status_logs(self, asset_id: int) -> list[dict]:
        return []

    def delete(self, asset_id: int) -> None:
        if asset_id not in self._items:
            raise LookupError("Equipo no encontrado")
        del self._items[asset_id]
