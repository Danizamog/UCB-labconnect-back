from app.infrastructure.pocketbase_base import PocketBaseClient
from app.infrastructure.repositories.stock_item_repository import StockItemRepository
from app.infrastructure.repositories.supply_reservation_repository import SupplyReservationRepository

_pb_client = PocketBaseClient()

stock_item_repo = StockItemRepository(_pb_client)
supply_reservation_repo = SupplyReservationRepository(_pb_client)


def close_resources() -> None:
    _pb_client.close()
