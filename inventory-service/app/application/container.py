from app.infrastructure.pocketbase_base import PocketBaseClient
from app.infrastructure.repositories.area_repository import AreaRepository
from app.infrastructure.repositories.laboratory_repository import LaboratoryRepository
from app.infrastructure.repositories.asset_repository import AssetRepository
from app.infrastructure.repositories.stock_item_repository import StockItemRepository

_pb_client = PocketBaseClient()

area_repo = AreaRepository(_pb_client)
laboratory_repo = LaboratoryRepository(_pb_client)
asset_repo = AssetRepository(_pb_client)
stock_item_repo = StockItemRepository(_pb_client)
