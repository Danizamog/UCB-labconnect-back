from __future__ import annotations

from datetime import date as dt_date, time as dt_time, datetime as dt_datetime
from typing import Optional, List

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Time, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PracticeRequest(Base):
    __tablename__ = "practice_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False)

    laboratory_id: Mapped[int] = mapped_column(ForeignKey("laboratories.id"), nullable=False)
    date: Mapped[dt_date] = mapped_column(Date, nullable=False)
    start_time: Mapped[dt_time] = mapped_column(Time, nullable=False)
    end_time: Mapped[dt_time] = mapped_column(Time, nullable=False)

    needs_support: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    support_topic: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    created_at: Mapped[dt_datetime] = mapped_column(DateTime, default=dt_datetime.utcnow, nullable=False)

    laboratory = relationship("Laboratory")
    materials: Mapped[List["PracticeMaterial"]] = relationship(
        "PracticeMaterial",
        back_populates="practice_request",
        cascade="all, delete-orphan",
    )