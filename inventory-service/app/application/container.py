from app.core.config import settings
from app.infrastructure.pocketbase_base import PocketBaseClient
from app.infrastructure.repositories.area_repository import AreaRepository
from app.infrastructure.repositories.asset_maintenance_repository import AssetMaintenanceRepository
from app.infrastructure.repositories.laboratory_repository import LaboratoryRepository
from app.infrastructure.repositories.asset_repository import AssetRepository
from app.infrastructure.repositories.loan_record_repository import LoanRecordRepository
from app.infrastructure.repositories.stock_item_repository import StockItemRepository
from app.infrastructure.repositories.user_directory_repository import UserDirectoryRepository

_pb_client = PocketBaseClient()

area_repo = AreaRepository(_pb_client)
laboratory_repo = LaboratoryRepository(_pb_client)
asset_repo = AssetRepository(_pb_client)
asset_maintenance_repo = AssetMaintenanceRepository(_pb_client, asset_repo=asset_repo)
user_directory_repo = UserDirectoryRepository(
    postgres_url=settings.postgres_url,
    namespace=settings.local_data_namespace,
    auth_service_url=settings.auth_service_url,
)
loan_record_repo = LoanRecordRepository(
    _pb_client,
    asset_repo=asset_repo,
    asset_maintenance_repo=asset_maintenance_repo,
    user_directory_repo=user_directory_repo,
)
stock_item_repo = StockItemRepository(_pb_client)
