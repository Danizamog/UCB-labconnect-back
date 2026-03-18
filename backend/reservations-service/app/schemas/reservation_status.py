from pydantic import BaseModel


class PracticeStatusUpdate(BaseModel):
    status: str