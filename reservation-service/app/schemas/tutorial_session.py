from __future__ import annotations

from pydantic import BaseModel, Field


class TutorialEnrollmentResponse(BaseModel):
    student_id: str
    student_name: str
    student_email: str = ""
    created_at: str


class TutorialSessionCreate(BaseModel):
    topic: str
    description: str = ""
    laboratory_id: str = ""
    location: str = ""
    session_date: str
    start_time: str
    end_time: str
    max_students: int
    tutor_id: str | None = None
    tutor_name: str | None = None
    tutor_email: str | None = None
    is_published: bool | None = None


class TutorialSessionUpdate(BaseModel):
    topic: str | None = None
    description: str | None = None
    laboratory_id: str | None = None
    location: str | None = None
    session_date: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    max_students: int | None = None
    tutor_id: str | None = None
    tutor_name: str | None = None
    tutor_email: str | None = None
    is_published: bool | None = None


class TutorialSessionResponse(BaseModel):
    id: str
    tutor_id: str
    tutor_name: str
    tutor_email: str = ""
    topic: str
    description: str
    laboratory_id: str = ""
    location: str
    session_date: str
    start_time: str
    end_time: str
    start_at: str
    end_at: str
    max_students: int
    is_published: bool
    enrolled_students: list[TutorialEnrollmentResponse] = Field(default_factory=list)
    created: str
    updated: str

    @property
    def enrolled_count(self) -> int:
        return len(self.enrolled_students)

    @property
    def seats_left(self) -> int:
        remaining = self.max_students - self.enrolled_count
        return remaining if remaining > 0 else 0
