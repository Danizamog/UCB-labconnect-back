from app.domain.entities.stock_item import StockItem


class InMemoryStockRepository:
    def __init__(self) -> None:
        self._items: dict[int, StockItem] = {}
        self._id_counter = 1

    def list_all(self) -> list[StockItem]:
        return sorted(self._items.values(), key=lambda item: item.id, reverse=True)

    def create(self, item: StockItem) -> StockItem:
        item.id = self._id_counter
        self._items[self._id_counter] = item
        self._id_counter += 1
        return item

    def get_by_id(self, item_id: int) -> StockItem | None:
        return self._items.get(item_id)

    def update(self, item: StockItem) -> StockItem:
        self._items[item.id] = item
        return item
