from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.db.base import Base


class PracticeMaterial(Base):
    __tablename__ = "practice_materials"

    id = Column(Integer, primary_key=True, index=True)
    practice_request_id = Column(Integer, ForeignKey("practice_requests.id"), nullable=False, index=True)
    asset_id = Column(Integer, nullable=False)
    material_name = Column(String(255), nullable=False)
    quantity = Column(Integer, nullable=False)

    practice_request = relationship("PracticeRequest", back_populates="materials")
