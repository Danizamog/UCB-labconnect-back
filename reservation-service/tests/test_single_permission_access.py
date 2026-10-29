import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from app.api.v1.endpoints import reservations, blocks
from app.realtime.manager import ClientContext, _user_can_receive, _visible_payload


@pytest.mark.parametrize('permission', ['gestionar_reservas','gestionar_accesos_laboratorio','gestionar_reglas_reserva','aprobar_tutorias','aprobar_clases','*',''])
@pytest.mark.parametrize('function,required,extra', [
    ('update_reservation_status','gestionar_reservas',{'body':SimpleNamespace(status='approved')}),
    ('register_reservation_entry','gestionar_accesos_laboratorio',{'body':SimpleNamespace()}),
    ('register_reservation_exit','gestionar_accesos_laboratorio',{}),
    ('mark_reservation_absent','gestionar_accesos_laboratorio',{}),
])
def test_each_mutation_requires_its_own_permission(monkeypatch, permission, function, required, extra):
    repo = SimpleNamespace(aget_by_id=AsyncMock(return_value=None))
    monkeypatch.setattr(reservations,'lab_reservation_repo',repo)
    monkeypatch.setattr(reservations,'lab_access_session_repo',SimpleNamespace(find_open_by_id_or_reservation=lambda _: None))
    actor = {'user_id':'operator','role':'Administrador','permissions':[permission] if permission else []}
    with pytest.raises(HTTPException) as error:
        asyncio.run(getattr(reservations,function)('missing',current_user=actor,**extra))
    assert error.value.status_code == (404 if permission == required else 403)
    assert repo.aget_by_id.await_count == (1 if permission == required else 0)


def test_structure_permission_alone_does_not_expose_other_users_reservations():
    actor = {'user_id':'operator','permissions':['gestionar_estructura_laboratorios']}
    rows = [SimpleNamespace(requested_by='other',laboratory_id='lab-1')]
    assert reservations._filter_reservations_for_user(rows,actor) == []


@pytest.mark.parametrize('permission', ['gestionar_reservas','gestionar_accesos_laboratorio','aprobar_clases',''])
def test_other_permissions_cannot_create_block(monkeypatch,permission):
    actor = {'user_id':'operator','role':'Administrador','permissions':[permission]}
    with pytest.raises(HTTPException) as error:
        asyncio.run(blocks.create_block(SimpleNamespace(),current_user=actor))
    assert error.value.status_code == 403


@pytest.mark.parametrize('permission', ['gestionar_reglas_reserva','gestionar_horarios_laboratorio','aprobar_clases','gestionar_penalizaciones','*',''])
def test_unrelated_realtime_permissions_never_expose_private_reservation_data(permission):
    client = ClientContext(websocket=None, user_id='observer', role='Administrador', permissions=frozenset([permission]))
    payload = {'topic':'lab_reservation','record':{'id':'r1','laboratory_id':'lab-1','requested_by':'owner',
               'requested_by_email':'private@ucb.edu.bo','notes':'private notes','start_at':'2026-11-01T08:00:00','status':'approved'}}
    assert _user_can_receive(client,payload) is True
    assert set(_visible_payload(client,payload)['record']) == {'id','laboratory_id','start_at','status'}


def test_realtime_reservation_manager_scope_cannot_be_changed_by_subscription():
    client = ClientContext(websocket=None,user_id='operator',permissions=frozenset(['gestionar_reservas']),
                           laboratory_ids=frozenset(['lab-2']),managed_laboratory_ids=frozenset(['lab-1']))
    event = {'topic':'lab_reservation','record':{'id':'r','laboratory_id':'lab-2','requested_by':'other','notes':'secret'}}
    assert 'notes' not in _visible_payload(client,event)['record']
    client.laboratory_ids = frozenset(['lab-1'])
    event['record']['laboratory_id'] = 'lab-1'
    assert _visible_payload(client,event)['record']['notes'] == 'secret'


def test_realtime_notification_for_another_user_is_not_sent_to_admin_role():
    client = ClientContext(websocket=None,user_id='admin',role='Administrador',permissions=frozenset(['gestionar_reservas','gestionar_estructura_laboratorios']))
    assert _user_can_receive(client,{'topic':'user_notification','recipients':['other'], 'record':{'recipient_user_id':'other'}}) is False


def test_realtime_tutorial_does_not_publish_pending_sessions_or_attendance():
    client = ClientContext(websocket=None,user_id='student')
    event = {'topic':'tutorial_session','record':{'id':'t','tutor_id':'teacher','approval_status':'pending','is_published':False,'enrolled_students':[{'student_email':'private'}]}}
    assert _user_can_receive(client,event) is False
    event['record'].update(approval_status='approved',is_published=True)
    assert _user_can_receive(client,event) is True
    assert 'enrolled_students' not in _visible_payload(client,event)['record']
