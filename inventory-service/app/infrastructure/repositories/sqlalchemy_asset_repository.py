from app.db.session import SessionLocal
from app.domain.entities.asset import Asset as AssetEntity
from app.models.asset import Asset as AssetModel


class SQLAlchemyAssetRepository:
    def _to_entity(self, model: AssetModel) -> AssetEntity:
        return AssetEntity(
            id=model.id,
            name=model.name,
            category=model.category,
            description=model.description,
            serial_number=model.serial_number,
            laboratory_id=model.laboratory_id,
            status=model.status,
        )

    def list_all(self) -> list[AssetEntity]:
        with SessionLocal() as db:
            rows = db.query(AssetModel).order_by(AssetModel.id.desc()).all()
            return [self._to_entity(row) for row in rows]

    def create(self, asset: AssetEntity) -> AssetEntity:
        with SessionLocal() as db:
            row = AssetModel(
                name=asset.name,
                category=asset.category,
                description=asset.description,
                serial_number=asset.serial_number,
                laboratory_id=asset.laboratory_id,
                status=asset.status,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return self._to_entity(row)

    def get_by_id(self, asset_id: int) -> AssetEntity | None:
        with SessionLocal() as db:
            row = db.query(AssetModel).filter(AssetModel.id == asset_id).first()
            if not row:
                return None
            return self._to_entity(row)

    def update(self, asset: AssetEntity) -> AssetEntity:
        with SessionLocal() as db:
            row = db.query(AssetModel).filter(AssetModel.id == asset.id).first()
            if not row:
                raise LookupError("Equipo no encontrado")

            row.name = asset.name
            row.category = asset.category
            row.description = asset.description
            row.serial_number = asset.serial_number
            row.laboratory_id = asset.laboratory_id
            row.status = asset.status

            db.commit()
            db.refresh(row)
            return self._to_entity(row)
