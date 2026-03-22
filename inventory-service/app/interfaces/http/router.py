from fastapi import APIRouter, HTTPException, status

from app.application.container import asset_use_cases, stock_use_cases
from app.interfaces.http.schemas.inventory import (
    AssetCreate,
    AssetOut,
    AssetStatusUpdate,
    AssetUpdate,
    StockItemCreate,
    StockItemOut,
    StockItemUpdate,
    StockQuantityUpdate,
)

api_router = APIRouter(prefix="/v1/inventory")

assets_router = APIRouter(prefix="/assets", tags=["assets"])


@assets_router.get("/", response_model=list[AssetOut])
def list_assets():
    return asset_use_cases.list_assets()


@assets_router.post("/", response_model=AssetOut, status_code=status.HTTP_201_CREATED)
def create_asset(payload: AssetCreate):
    try:
        return asset_use_cases.create_asset(
            name=payload.name,
            category=payload.category,
            description=payload.description,
            serial_number=payload.serial_number,
            laboratory_id=payload.laboratory_id,
            status=payload.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@assets_router.put("/{asset_id}", response_model=AssetOut)
def update_asset(asset_id: int, payload: AssetUpdate):
    try:
        return asset_use_cases.update_asset(
            asset_id=asset_id,
            name=payload.name,
            category=payload.category,
            description=payload.description,
            serial_number=payload.serial_number,
            laboratory_id=payload.laboratory_id,
            status=payload.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@assets_router.patch("/{asset_id}/status", response_model=AssetOut)
def update_asset_status(asset_id: int, payload: AssetStatusUpdate):
    try:
        return asset_use_cases.update_asset_status(asset_id=asset_id, status=payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


stock_router = APIRouter(prefix="/stock-items", tags=["stock-items"])


@stock_router.get("/", response_model=list[StockItemOut])
def list_stock_items():
    return stock_use_cases.list_items()


@stock_router.post("/", response_model=StockItemOut, status_code=status.HTTP_201_CREATED)
def create_stock_item(payload: StockItemCreate):
    return stock_use_cases.create_item(
        name=payload.name,
        category=payload.category,
        unit=payload.unit,
        quantity_available=payload.quantity_available,
        minimum_stock=payload.minimum_stock,
        laboratory_id=payload.laboratory_id,
        description=payload.description,
    )


@stock_router.put("/{item_id}", response_model=StockItemOut)
def update_stock_item(item_id: int, payload: StockItemUpdate):
    try:
        return stock_use_cases.update_item(
            item_id=item_id,
            name=payload.name,
            category=payload.category,
            unit=payload.unit,
            quantity_available=payload.quantity_available,
            minimum_stock=payload.minimum_stock,
            laboratory_id=payload.laboratory_id,
            description=payload.description,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@stock_router.patch("/{item_id}/quantity", response_model=StockItemOut)
def update_stock_quantity(item_id: int, payload: StockQuantityUpdate):
    try:
        return stock_use_cases.update_quantity(
            item_id=item_id,
            quantity_available=payload.quantity_available,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


api_router.include_router(assets_router)
api_router.include_router(stock_router)
