from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db.base import Base


class Laboratory(Base):
    __tablename__ = "laboratories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False, unique=True, index=True)
    location = Column(String(160), nullable=False)
    capacity = Column(Integer, nullable=False, default=1)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    area_id = Column(Integer, ForeignKey("areas.id"), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    area = relationship("Area", back_populates="laboratories")
    practice_requests = relationship("PracticeRequest", back_populates="laboratory")
    class_sessions = relationship("ClassSession", back_populates="laboratory")
    class_tutorials = relationship("ClassTutorial", back_populates="laboratory")
