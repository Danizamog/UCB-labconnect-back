from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db.base import Base


class Laboratory(Base):
    __tablename__ = "laboratories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False, index=True)
    location = Column(String(120), nullable=False)
    capacity = Column(Integer, nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    area_id = Column(Integer, ForeignKey("areas.id"), nullable=False, index=True)

    area = relationship("Area", back_populates="laboratories")
    practice_requests = relationship("PracticeRequest", back_populates="laboratory")