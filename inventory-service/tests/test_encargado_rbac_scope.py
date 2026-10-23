from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import asset_maintenance, stock_items
from app.schemas.asset_maintenance import AssetMaintenanceTicketClose, AssetMaintenanceTicketCreate
from app.schemas.stock_item import StockItemCreate


ENCARGADO = {
    "user_id": "enc-1",
    "permissions": ["gestionar_reservas_materiales", "registrar_tickets_equipo"],
}


def test_encargado_can_report_ticket_only_for_assigned_lab():
    ticket = AssetMaintenanceTicketCreate(ticket_type="damage", title="Falla", description="Equipo no enciende")
    repo = SimpleNamespace(create=lambda *args, **kwargs: "created")
    with patch.object(asset_maintenance, "resolve_accessible_lab_ids", return_value=["lab-1"]), \
         patch.object(asset_maintenance, "asset_repo", SimpleNamespace(get_by_id=lambda asset_id: SimpleNamespace(laboratory_id="lab-1"))), \
         patch.object(asset_maintenance, "asset_maintenance_repo", repo):
        assert asset_maintenance.create_ticket("asset-1", ticket, current_user=ENCARGADO) == "created"

    with patch.object(asset_maintenance, "resolve_accessible_lab_ids", return_value=["lab-1"]), \
         patch.object(asset_maintenance, "asset_repo", SimpleNamespace(get_by_id=lambda asset_id: SimpleNamespace(laboratory_id="lab-2"))):
        with pytest.raises(HTTPException) as error:
            asset_maintenance.create_ticket("asset-2", ticket, current_user=ENCARGADO)
        assert error.value.status_code == 404

    with pytest.raises(HTTPException) as error:
        asset_maintenance.close_ticket("ticket-1", AssetMaintenanceTicketClose(resolution_notes="Listo"), current_user=ENCARGADO)
    assert error.value.status_code == 403


def test_encargado_cannot_create_stock_or_register_purchase():
    with pytest.raises(HTTPException) as error:
        stock_items.create_stock_item(StockItemCreate(name="Reactivo", laboratory_id="lab-1"), current_user=ENCARGADO)
    assert error.value.status_code == 403

    with pytest.raises(HTTPException) as error:
        stock_items.create_movement("item-1", stock_items.StockMovementCreate(movement_type="entry", quantity=1), current_user=ENCARGADO)
    assert error.value.status_code == 403


def test_encargado_cannot_receive_more_than_recorded_loans():
    item = SimpleNamespace(id="item-1", laboratory_id="lab-1", quantity_available=4, name="Material")
    history = [SimpleNamespace(notes="[PRESTAMO ENCARGADO] Grupo 1", quantity_change=-2)]
    with patch.object(stock_items, "resolve_accessible_lab_ids", return_value=["lab-1"]), \
         patch.object(stock_items, "stock_item_repo", SimpleNamespace(get_by_id_fresh=lambda _id: item)), \
         patch.object(stock_items, "stock_movement_repo", SimpleNamespace(list_all_for_item=lambda _id: history)):
        with pytest.raises(HTTPException) as error:
            stock_items.create_movement(
                "item-1",
                stock_items.StockMovementCreate(movement_type="return", quantity=3, notes="Grupo 1"),
                current_user=ENCARGADO,
            )
    assert error.value.status_code == 409

