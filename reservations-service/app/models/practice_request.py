from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text, Time
from sqlalchemy.orm import relationship

from app.db.base import Base


class PracticeRequest(Base):
    __tablename__ = "practice_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(120), nullable=False, index=True)
    username = Column(String(255), nullable=False)
    subject_name = Column(String(160), nullable=True)
    laboratory_id = Column(Integer, ForeignKey("laboratories.id"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    needs_support = Column(Boolean, nullable=False, default=False)
    support_topic = Column(String(255), nullable=True)
    notes = Column(Text, nullable=False)
    review_comment = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    status_updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    user_notification_read = Column(Boolean, nullable=False, default=True)

    laboratory = relationship("Laboratory", back_populates="practice_requests")
    materials = relationship(
        "PracticeMaterial",
        back_populates="practice_request",
        cascade="all, delete-orphan",
    )
