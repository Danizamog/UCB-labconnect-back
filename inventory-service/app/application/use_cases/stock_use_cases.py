from app.domain.entities.stock_item import StockItem
from app.domain.repositories.stock_repository import StockRepository


class StockUseCases:
    def __init__(self, repository: StockRepository):
        self.repository = repository

    def list_items(self) -> list[StockItem]:
        return self.repository.list_all()

    def create_item(
        self,
        name: str,
        category: str,
        unit: str,
        quantity_available: float,
        minimum_stock: float,
        laboratory_id: int | None,
        description: str | None,
    ) -> StockItem:
        item = StockItem(
            id=0,
            name=name,
            category=category,
            unit=unit,
            quantity_available=quantity_available,
            minimum_stock=minimum_stock,
            laboratory_id=laboratory_id,
            description=description,
        )
        return self.repository.create(item)

    def update_item(
        self,
        item_id: int,
        name: str,
        category: str,
        unit: str,
        quantity_available: float,
        minimum_stock: float,
        laboratory_id: int | None,
        description: str | None,
    ) -> StockItem:
        item = self.repository.get_by_id(item_id)
        if not item:
            raise LookupError("Reactivo no encontrado")

        item.name = name
        item.category = category
        item.unit = unit
        item.quantity_available = quantity_available
        item.minimum_stock = minimum_stock
        item.laboratory_id = laboratory_id
        item.description = description
        return self.repository.update(item)

    def update_quantity(self, item_id: int, quantity_available: float) -> StockItem:
        item = self.repository.get_by_id(item_id)
        if not item:
            raise LookupError("Reactivo no encontrado")

        item.quantity_available = quantity_available
        return self.repository.update(item)
