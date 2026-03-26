from app.core.asset_states import AssetStatus
from app.domain.entities.asset import Asset
from app.domain.repositories.asset_repository import AssetRepository


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
        location: str,
        description: str | None,
        serial_number: str | None,
        laboratory_id: int | None,
        status: str | AssetStatus,
    ) -> Asset:
        normalized_location = location.strip()
        if not normalized_location:
            raise ValueError("La ubicacion del equipo es obligatoria")
        normalized_status = self._normalize_status(status)
        if not AssetStatus.is_valid(normalized_status):
            raise ValueError(
                f"Estado invÃ¡lido. Usa: {', '.join(sorted(AssetStatus.get_all_values()))}"
            )

        asset = Asset(
            id=0,
            name=name,
            category=category,
            location=normalized_location,
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
        location: str,
        description: str | None,
        serial_number: str | None,
        laboratory_id: int | None,
        status: str | AssetStatus,
        changed_by: str | None = None,
    ) -> Asset:
        normalized_location = location.strip()
        if not normalized_location:
            raise ValueError("La ubicacion del equipo es obligatoria")
        normalized_status = self._normalize_status(status)
        if not AssetStatus.is_valid(normalized_status):
            raise ValueError(
                f"Estado invÃ¡lido. Usa: {', '.join(sorted(AssetStatus.get_all_values()))}"
            )

        asset = self.repository.get_by_id(asset_id)
        if not asset:
            raise LookupError("Equipo no encontrado")

        asset.name = name
        asset.category = category
        asset.location = normalized_location
        asset.description = description
        asset.serial_number = serial_number
        asset.laboratory_id = laboratory_id
        asset.status = normalized_status
        return self.repository.update(asset, changed_by=changed_by)

    def update_asset_status(self, asset_id: int, status: str | AssetStatus, changed_by: str | None = None) -> Asset:
        normalized_status = self._normalize_status(status)
        if not AssetStatus.is_valid(normalized_status):
            raise ValueError(
                f"Estado invÃ¡lido. Usa: {', '.join(sorted(AssetStatus.get_all_values()))}"
            )

        asset = self.repository.get_by_id(asset_id)
        if not asset:
            raise LookupError("Equipo no encontrado")

        asset.status = normalized_status
        return self.repository.update(
            asset,
            changed_by=changed_by,
            notes="Cambio de estado desde panel administrativo.",
        )

    def list_asset_status_logs(self, asset_id: int) -> list[dict]:
        asset = self.repository.get_by_id(asset_id)
        if not asset:
            raise LookupError("Equipo no encontrado")
        return self.repository.list_status_logs(asset_id)

    def delete_asset(self, asset_id: int) -> None:
        asset = self.repository.get_by_id(asset_id)
        if not asset:
            raise LookupError("Equipo no encontrado")

        self.repository.delete(asset_id)
