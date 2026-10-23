from types import SimpleNamespace
from unittest.mock import patch

from app.api.v1.endpoints import supply_reservations


def test_encargado_only_lists_requests_for_assigned_laboratory():
    user = {"user_id": "enc-1", "permissions": ["gestionar_reservas_materiales"]}
    records = [
        SimpleNamespace(laboratory_id="lab-1"),
        SimpleNamespace(laboratory_id="lab-2"),
    ]
    with patch.object(supply_reservations, "_managed_laboratory_ids", return_value={"lab-1"}), \
         patch.object(supply_reservations, "supply_reservation_repo", SimpleNamespace(list_all=lambda **kwargs: records)):
        result = supply_reservations.list_supply_reservations(
            status_filter=None, tutorial_session_id=None, stock_item_id=None,
            lab_reservation_id=None, current_user=user,
        )
    assert [item.laboratory_id for item in result] == ["lab-1"]
