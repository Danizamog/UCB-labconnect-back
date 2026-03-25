from datetime import datetime

from app.db.session import SessionLocal
from app.domain.entities.asset import Asset as AssetEntity
from app.models.asset import Asset as AssetModel
from app.models.asset_status_log import AssetStatusLog


class SQLAlchemyAssetRepository:
    def _to_entity(self, model: AssetModel) -> AssetEntity:
        return AssetEntity(
            id=model.id,
            name=model.name,
            category=model.category,
            location=model.location,
            description=model.description,
            serial_number=model.serial_number,
            laboratory_id=model.laboratory_id,
            status=model.status,
            status_updated_at=model.status_updated_at,
            status_updated_by=model.status_updated_by,
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
                location=asset.location,
                description=asset.description,
                serial_number=asset.serial_number,
                laboratory_id=asset.laboratory_id,
                status=asset.status,
                status_updated_at=datetime.utcnow(),
                status_updated_by="system",
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

    def update(self, asset: AssetEntity, changed_by: str | None = None, notes: str | None = None) -> AssetEntity:
        with SessionLocal() as db:
            row = db.query(AssetModel).filter(AssetModel.id == asset.id).first()
            if not row:
                raise LookupError("Equipo no encontrado")

            previous_status = row.status
            row.name = asset.name
            row.category = asset.category
            row.location = asset.location
            row.description = asset.description
            row.serial_number = asset.serial_number
            row.laboratory_id = asset.laboratory_id
            row.status = asset.status
            row.updated_at = datetime.utcnow()

            if previous_status != asset.status:
                row.status_updated_at = datetime.utcnow()
                row.status_updated_by = changed_by or "system"
                db.add(
                    AssetStatusLog(
                        asset_id=row.id,
                        previous_status=previous_status,
                        next_status=asset.status,
                        changed_by=changed_by or "system",
                        notes=notes,
                    )
                )

            db.commit()
            db.refresh(row)
            return self._to_entity(row)

    def list_status_logs(self, asset_id: int) -> list[dict]:
        with SessionLocal() as db:
            rows = (
                db.query(AssetStatusLog)
                .filter(AssetStatusLog.asset_id == asset_id)
                .order_by(AssetStatusLog.changed_at.desc(), AssetStatusLog.id.desc())
                .all()
            )
            return [
                {
                    "id": row.id,
                    "asset_id": row.asset_id,
                    "previous_status": row.previous_status,
                    "next_status": row.next_status,
                    "changed_by": row.changed_by,
                    "changed_at": row.changed_at,
                    "notes": row.notes,
                }
                for row in rows
            ]

    def delete(self, asset_id: int) -> None:
        with SessionLocal() as db:
            row = db.query(AssetModel).filter(AssetModel.id == asset_id).first()
            if not row:
                raise LookupError("Equipo no encontrado")

            db.delete(row)
            db.commit()
