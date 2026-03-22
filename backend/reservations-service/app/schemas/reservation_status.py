from pydantic import BaseModel


class PracticeStatusUpdate(BaseModel):
    status: str
    review_comment: str | None = None
