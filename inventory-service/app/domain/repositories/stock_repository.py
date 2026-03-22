from typing import Protocol

from app.domain.entities.stock_item import StockItem


class StockRepository(Protocol):
    def list_all(self) -> list[StockItem]:
        ...

    def create(self, item: StockItem) -> StockItem:
        ...

    def get_by_id(self, item_id: int) -> StockItem | None:
        ...

    def update(self, item: StockItem) -> StockItem:
        ...
