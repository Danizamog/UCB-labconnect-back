from typing import List, Optional
from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel

router = APIRouter(prefix="/api/classes", tags=["classes"])

class ClassCreate(BaseModel):
    laboratory_id: int
    date: str
    start_time: str
    end_time: str
    subject_name: str
    teacher_name: str
    needs_support: bool = False
    support_topic: Optional[str] = None
    notes: Optional[str] = None

class ClassUpdate(BaseModel):
    laboratory_id: Optional[int] = None
    date: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    subject_name: Optional[str] = None
    teacher_name: Optional[Optional[str]] = None
    needs_support: Optional[bool] = None
    support_topic: Optional[str] = None
    notes: Optional[str] = None

@router.post("/")
def create_class(data: ClassCreate):
    if data.start_time >= data.end_time:
        raise HTTPException(status_code=400, detail="La hora de inicio debe ser menor que la de fin.")
    
    if data.needs_support and not data.support_topic:
        raise HTTPException(status_code=400, detail="Debe especificar el apoyo necesario.")
    
    return {"status": "success", "message": "Clase registrada", "data": data}

@router.put("/{class_id}")
def update_class(class_id: int, data: ClassUpdate):
    return {"status": "success", "message": f"Clase {class_id} actualizada", "data": data}
