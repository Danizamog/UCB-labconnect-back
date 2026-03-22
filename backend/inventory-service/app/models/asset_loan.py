from __future__ import annotations

from datetime import datetime as dt_datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AssetLoan(Base):
    __tablename__ = "asset_loans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False, index=True)
    borrower_name: Mapped[str] = mapped_column(String(120), nullable=False)
    borrower_email: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt_datetime] = mapped_column(DateTime, default=dt_datetime.utcnow, nullable=False)
    due_at: Mapped[dt_datetime | None] = mapped_column(DateTime, nullable=True)
    returned_at: Mapped[dt_datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="loaned", nullable=False)
