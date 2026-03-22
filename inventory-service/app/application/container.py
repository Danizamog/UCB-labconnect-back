from app.application.use_cases.asset_use_cases import AssetUseCases
from app.application.use_cases.stock_use_cases import StockUseCases
from app.infrastructure.repositories.in_memory_asset_repository import InMemoryAssetRepository
from app.infrastructure.repositories.in_memory_stock_repository import InMemoryStockRepository

asset_repository = InMemoryAssetRepository()
stock_repository = InMemoryStockRepository()

asset_use_cases = AssetUseCases(repository=asset_repository)
stock_use_cases = StockUseCases(repository=stock_repository)
