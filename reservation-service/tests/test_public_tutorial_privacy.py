from app.api.v1.endpoints.tutorial_sessions import _visible_session
from app.schemas.tutorial_session import TutorialEnrollmentResponse, TutorialSessionResponse


def session():
    return TutorialSessionResponse(id='tutorial',tutor_id='teacher',tutor_name='Teacher',topic='Topic',description='',location='Lab',session_date='2026-11-02',start_time='16:00',end_time='16:45',start_at='2026-11-02T16:00:00',end_at='2026-11-02T16:45:00',max_students=10,is_published=True,approval_status='approved',created='',updated='',tutor_observation='Private observation',enrolled_students=[TutorialEnrollmentResponse(student_id='student',student_name='Private name',student_email='private@example.invalid',created_at='2026-10-30')])


def test_guest_sees_capacity_without_student_data():
    public=_visible_session(session(),{'user_id':'guest','role':'Invitado'})
    assert public.enrolled_students==[]
    assert public.tutor_observation==''
    assert public.model_dump()['enrolled_count']==1
    assert public.model_dump()['seats_left']==9


def test_student_can_see_own_enrollment():
    assert len(_visible_session(session(),{'user_id':'student'}).enrolled_students)==1


def test_owner_keeps_attendance_details():
    assert _visible_session(session(),{'user_id':'teacher'}).tutor_observation=='Private observation'
