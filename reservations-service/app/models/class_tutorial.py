from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text, Time
from sqlalchemy.orm import relationship

from app.db.base import Base


class ClassTutorial(Base):
    __tablename__ = "clases_tutorias"

    id = Column(Integer, primary_key=True, index=True)
    laboratory_id = Column(Integer, ForeignKey("laboratories.id"), nullable=False, index=True)
    session_type = Column(String(24), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    title = Column(String(160), nullable=False)
    facilitator_name = Column(String(160), nullable=False)
    target_group = Column(String(160), nullable=True)
    academic_unit = Column(String(160), nullable=True)
    needs_support = Column(Boolean, nullable=False, default=False)
    support_topic = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    laboratory = relationship("Laboratory", back_populates="class_tutorials")
