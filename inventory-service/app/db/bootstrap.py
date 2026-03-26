from datetime import datetime, timedelta

from sqlalchemy import inspect, text

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.asset import Asset
from app.models.asset_status_log import AssetStatusLog
from app.models.loan_record import LoanRecord
from app.models.stock_movement import StockMovement
from app.models.stock_item import StockItem


def ensure_inventory_schema() -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "loan_records" not in table_names:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("loan_records")}
    statements: list[str] = []

    if "source_type" not in existing_columns:
        statements.append("ALTER TABLE loan_records ADD COLUMN source_type VARCHAR(30) DEFAULT 'manual'")
    if "practice_request_id" not in existing_columns:
        statements.append("ALTER TABLE loan_records ADD COLUMN practice_request_id INTEGER")
    if "return_condition" not in existing_columns:
        statements.append("ALTER TABLE loan_records ADD COLUMN return_condition VARCHAR(30)")
    if "incident_notes" not in existing_columns:
        statements.append("ALTER TABLE loan_records ADD COLUMN incident_notes TEXT")

    if "assets" in table_names:
        asset_columns = {column["name"] for column in inspector.get_columns("assets")}
        if "location" not in asset_columns:
            statements.append("ALTER TABLE assets ADD COLUMN location VARCHAR(160) DEFAULT 'Ubicacion pendiente'")
        if "updated_at" not in asset_columns:
            statements.append("ALTER TABLE assets ADD COLUMN updated_at DATETIME")
        if "status_updated_at" not in asset_columns:
            statements.append("ALTER TABLE assets ADD COLUMN status_updated_at DATETIME")
        if "status_updated_by" not in asset_columns:
            statements.append("ALTER TABLE assets ADD COLUMN status_updated_by VARCHAR(160)")

    if not statements:
        with engine.begin() as connection:
            if "assets" in table_names:
                connection.execute(
                    text(
                        "UPDATE assets SET location = CASE "
                        "WHEN location IS NULL OR TRIM(location) = '' THEN "
                        "CASE "
                        "WHEN laboratory_id IS NULL THEN 'Almacen general de inventario' "
                        "ELSE 'Equipo ubicado en laboratorio asignado' "
                        "END "
                        "ELSE location END"
                    )
                )
                connection.execute(text("UPDATE assets SET updated_at = COALESCE(updated_at, created_at)"))
                connection.execute(
                    text(
                        "UPDATE assets SET status_updated_at = COALESCE(status_updated_at, created_at), "
                        "status_updated_by = COALESCE(status_updated_by, 'system')"
                    )
                )
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        if "assets" in table_names:
            connection.execute(
                text(
                    "UPDATE assets SET location = CASE "
                    "WHEN location IS NULL OR TRIM(location) = '' THEN "
                    "CASE "
                    "WHEN laboratory_id IS NULL THEN 'Almacen general de inventario' "
                    "ELSE 'Equipo ubicado en laboratorio asignado' "
                    "END "
                    "ELSE location END"
                )
            )
            connection.execute(text("UPDATE assets SET updated_at = COALESCE(updated_at, created_at)"))
            connection.execute(
                text(
                    "UPDATE assets SET status_updated_at = COALESCE(status_updated_at, created_at), "
                    "status_updated_by = COALESCE(status_updated_by, 'system')"
                )
            )


def initialize_inventory_database() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_inventory_schema()

    with SessionLocal() as db:
        has_assets = db.query(Asset.id).first() is not None
        has_asset_status_logs = db.query(AssetStatusLog.id).first() is not None
        has_loans = db.query(LoanRecord.id).first() is not None
        has_stock_items = db.query(StockItem.id).first() is not None
        has_stock_movements = db.query(StockMovement.id).first() is not None

        if not has_assets:
            db.add_all(
                [
                    Asset(
                        name="Microscopio Binocular",
                        category="Microscopia",
                        location="Gabinete de Biologia - Estante 2",
                        description="Equipo de observacion para practicas de laboratorio.",
                        serial_number="MIC-001",
                        laboratory_id=3,
                        status="available",
                        status_updated_by="system",
                    ),
                    Asset(
                        name="Kit de Redes Cisco",
                        category="Redes",
                        location="Laboratorio de Redes - Rack principal",
                        description="Router y switches para practicas de topologias de red.",
                        serial_number="NET-014",
                        laboratory_id=1,
                        status="available",
                        status_updated_by="system",
                    ),
                    Asset(
                        name="Osciloscopio Digital",
                        category="Instrumentacion",
                        location="Laboratorio de Sistemas - Mesa de medicion 4",
                        description="Equipo de medicion para senales analogicas y digitales.",
                        serial_number="OSC-021",
                        laboratory_id=2,
                        status="maintenance",
                        status_updated_by="system",
                    ),
                ]
            )
        else:
            for asset in db.query(Asset).all():
                if asset.laboratory_id == 101:
                    asset.laboratory_id = 3
                elif asset.laboratory_id == 202:
                    asset.laboratory_id = 2
                if not asset.location or not asset.location.strip():
                    asset.location = (
                        "Almacen general de inventario"
                        if asset.laboratory_id is None
                        else "Equipo ubicado en laboratorio asignado"
                    )

        if not has_stock_items:
            db.add_all(
                [
                    StockItem(
                        name="Multimetro",
                        category="Instrumentacion",
                        unit="unidad",
                        quantity_available=12,
                        minimum_stock=4,
                        laboratory_id=2,
                        description="Instrumento para medicion electrica en practicas de sistemas.",
                    ),
                    StockItem(
                        name="Cable UTP",
                        category="Conectividad",
                        unit="rollo",
                        quantity_available=20,
                        minimum_stock=6,
                        laboratory_id=1,
                        description="Material para armado y pruebas de redes estructuradas.",
                    ),
                    StockItem(
                        name="Protoboard",
                        category="Electronica",
                        unit="unidad",
                        quantity_available=18,
                        minimum_stock=5,
                        laboratory_id=2,
                        description="Base para prototipado rapido de circuitos.",
                    ),
                    StockItem(
                        name="Reactivo de pH",
                        category="Quimica",
                        unit="frasco",
                        quantity_available=10,
                        minimum_stock=3,
                        laboratory_id=None,
                        description="Reactivo de uso transversal para practicas de laboratorio.",
                    ),
                ]
            )

        if not has_loans:
            now = datetime.utcnow()
            db.add(
                LoanRecord(
                    loan_type="material",
                    source_type="manual",
                    practice_request_id=None,
                    stock_item_id=1,
                    asset_id=None,
                    laboratory_id=2,
                    item_name="Multimetro",
                    item_category="Instrumentacion",
                    borrower_name="Coordinacion de Laboratorios",
                    borrower_email="coordinacion.lab@ucb.edu.bo",
                    borrower_role="Encargado",
                    purpose="Registro historico inicial del modulo de prestamos.",
                    quantity=1,
                    status="returned",
                    return_condition="ok",
                    notes="Semilla del sistema para activar el historial.",
                    return_notes="Entrega cerrada sin novedades.",
                    incident_notes=None,
                    approved_by="system",
                    returned_by="system",
                    loaned_at=now - timedelta(days=3),
                    due_at=now - timedelta(days=2),
                    returned_at=now - timedelta(days=2),
                )
            )

        if not has_stock_movements:
            for item in db.query(StockItem).all():
                if item.quantity_available <= 0:
                    continue
                db.add(
                    StockMovement(
                        stock_item_id=item.id,
                        movement_type="entry",
                        quantity_change=item.quantity_available,
                        quantity_before=0,
                        quantity_after=item.quantity_available,
                        reference_type="migration",
                        reference_id=item.id,
                        performed_by="system",
                        notes="Balance inicial migrado al historial de stock.",
                    )
                )

        if not has_asset_status_logs:
            for asset in db.query(Asset).all():
                db.add(
                    AssetStatusLog(
                        asset_id=asset.id,
                        previous_status=None,
                        next_status=asset.status,
                        changed_by=asset.status_updated_by or "system",
                        changed_at=asset.status_updated_at or asset.created_at,
                        notes="Estado inicial migrado al historial de equipos.",
                    )
                )

        db.commit()
