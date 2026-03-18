from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PracticeMaterial(Base):
    __tablename__ = "practice_materials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    practice_request_id: Mapped[int] = mapped_column(
        ForeignKey("practice_requests.id"),
        nullable=False
    )
    asset_id: Mapped[int] = mapped_column(Integer, nullable=False)
    material_name: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    practice_request: Mapped["PracticeRequest"] = relationship(
        "PracticeRequest",
        back_populates="materials"
    )