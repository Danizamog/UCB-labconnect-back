from app.domain.entities.asset import Asset
from app.domain.repositories.asset_repository import AssetRepository
from app.core.asset_states import AssetStatus


class AssetUseCases:
    def __init__(self, repository: AssetRepository):
        self.repository = repository

    @staticmethod
    def _normalize_status(status: str | AssetStatus) -> str:
        if isinstance(status, AssetStatus):
            return status.value
        return str(status)

    def list_assets(self) -> list[Asset]:
        return self.repository.list_all()

    def create_asset(
        self,
        name: str,
        category: str,
        description: str | None,
        serial_number: str | None,
        laboratory_id: int | None,
        status: str | AssetStatus,
    ) -> Asset:
        normalized_status = self._normalize_status(status)
        if not AssetStatus.is_valid(normalized_status):
            raise ValueError(
                f"Estado inválido. Usa: {', '.join(sorted(AssetStatus.get_all_values()))}"
            )

        asset = Asset(
            id=0,
            name=name,
            category=category,
            description=description,
            serial_number=serial_number,
            laboratory_id=laboratory_id,
            status=normalized_status,
        )
        return self.repository.create(asset)

    def update_asset(
        self,
        asset_id: int,
        name: str,
        category: str,
        description: str | None,
        serial_number: str | None,
        laboratory_id: int | None,
        status: str | AssetStatus,
    ) -> Asset:
        normalized_status = self._normalize_status(status)
        if not AssetStatus.is_valid(normalized_status):
            raise ValueError(
                f"Estado inválido. Usa: {', '.join(sorted(AssetStatus.get_all_values()))}"
            )

        asset = self.repository.get_by_id(asset_id)
        if not asset:
            raise LookupError("Equipo no encontrado")

        asset.name = name
        asset.category = category
        asset.description = description
        asset.serial_number = serial_number
        asset.laboratory_id = laboratory_id
        asset.status = normalized_status
        return self.repository.update(asset)

    def update_asset_status(self, asset_id: int, status: str | AssetStatus) -> Asset:
        normalized_status = self._normalize_status(status)
        if not AssetStatus.is_valid(normalized_status):
            raise ValueError(
                f"Estado inválido. Usa: {', '.join(sorted(AssetStatus.get_all_values()))}"
            )

        asset = self.repository.get_by_id(asset_id)
        if not asset:
            raise LookupError("Equipo no encontrado")

        asset.status = normalized_status
        return self.repository.update(asset)
