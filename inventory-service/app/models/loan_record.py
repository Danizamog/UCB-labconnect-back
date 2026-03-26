from __future__ import annotations

from datetime import datetime as dt_datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LoanRecord(Base):
    __tablename__ = "loan_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    loan_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    practice_request_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    asset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stock_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    laboratory_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    item_name: Mapped[str] = mapped_column(String(120), nullable=False)
    item_category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    borrower_name: Mapped[str] = mapped_column(String(120), nullable=False)
    borrower_email: Mapped[str] = mapped_column(String(180), nullable=False)
    borrower_role: Mapped[str] = mapped_column(String(80), nullable=False, default="Estudiante")
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    return_condition: Mapped[str | None] = mapped_column(String(30), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    return_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    incident_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    returned_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    loaned_at: Mapped[dt_datetime] = mapped_column(DateTime, default=dt_datetime.utcnow, nullable=False)
    due_at: Mapped[dt_datetime] = mapped_column(DateTime, nullable=False)
    returned_at: Mapped[dt_datetime | None] = mapped_column(DateTime, nullable=True)
