from __future__ import annotations

from datetime import datetime as dt_datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StockItem(Base):
    __tablename__ = "stock_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity_available: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    minimum_stock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    laboratory_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt_datetime] = mapped_column(DateTime, default=dt_datetime.utcnow, nullable=False)