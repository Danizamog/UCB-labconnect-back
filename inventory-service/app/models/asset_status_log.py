from __future__ import annotations

from datetime import datetime as dt_datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AssetStatusLog(Base):
    __tablename__ = "asset_status_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    asset_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    previous_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    next_status: Mapped[str] = mapped_column(String(30), nullable=False)
    changed_by: Mapped[str] = mapped_column(String(160), nullable=False)
    changed_at: Mapped[dt_datetime] = mapped_column(DateTime, default=dt_datetime.utcnow, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
