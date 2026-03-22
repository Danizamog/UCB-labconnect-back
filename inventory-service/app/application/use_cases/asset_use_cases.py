from app.domain.entities.asset import Asset
from app.domain.repositories.asset_repository import AssetRepository

ALLOWED_ASSET_STATUS = {"available", "maintenance", "damaged"}


class AssetUseCases:
    def __init__(self, repository: AssetRepository):
        self.repository = repository

    def list_assets(self) -> list[Asset]:
        return self.repository.list_all()

    def create_asset(
        self,
        name: str,
        category: str,
        description: str | None,
        serial_number: str | None,
        laboratory_id: int | None,
        status: str,
    ) -> Asset:
        if status not in ALLOWED_ASSET_STATUS:
            raise ValueError("Estado inválido")

        asset = Asset(
            id=0,
            name=name,
            category=category,
            description=description,
            serial_number=serial_number,
            laboratory_id=laboratory_id,
            status=status,
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
        status: str,
    ) -> Asset:
        if status not in ALLOWED_ASSET_STATUS:
            raise ValueError("Estado inválido")

        asset = self.repository.get_by_id(asset_id)
        if not asset:
            raise LookupError("Equipo no encontrado")

        asset.name = name
        asset.category = category
        asset.description = description
        asset.serial_number = serial_number
        asset.laboratory_id = laboratory_id
        asset.status = status
        return self.repository.update(asset)

    def update_asset_status(self, asset_id: int, status: str) -> Asset:
        if status not in ALLOWED_ASSET_STATUS:
            raise ValueError("Estado inválido")

        asset = self.repository.get_by_id(asset_id)
        if not asset:
            raise LookupError("Equipo no encontrado")

        asset.status = status
        return self.repository.update(asset)
