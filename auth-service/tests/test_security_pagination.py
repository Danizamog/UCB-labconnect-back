from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.domain.security_query import SecurityQuery
from app.infrastructure.repositories.in_memory_user_repository import InMemoryUserRepository
from app.infrastructure.repositories.pocketbase_user_repository import PocketBaseUserRepository
from app.interfaces.http import router
from app.main import app


@pytest.fixture
def evidence(monkeypatch):
    repo = InMemoryUserRepository()
    monkeypatch.setattr(router, "user_repository", repo)
    app.dependency_overrides[router._get_current_payload] = lambda: {
        "user_id": "auditor", "permissions": ['consultar_auditoria_seguridad', 'consultar_eventos_autenticacion',
        'consultar_sesiones_usuarios', 'consultar_incidentes_seguridad', 'revisar_accesos_rbac']}
    yield TestClient(app), repo
    app.dependency_overrides.clear()


def add(repo, collection, index, **values):
    repo.create_security_record(collection, {"id": f"event-{index:04}",
        "created": (datetime.now(timezone.utc) - timedelta(seconds=500-index)).isoformat(), **values})


def test_full_history_pagination_exceeds_the_previous_100_record_limit(evidence):
    client, repo = evidence
    for i in range(245):
        add(repo, "security_audit_event", i, action="auth.login.succeeded", result="success", actor_email=f"user{i}@ucb.edu.bo")
    first = client.get('/v1/security/audit-events?paginated=true&per_page=20').json()
    assert first['totalItems'] == 245 and first['totalPages'] == 13
    last = client.get('/v1/security/audit-events', params={'paginated':True, 'per_page':20, 'page':13, 'snapshot_at':first['snapshotAt']}).json()
    assert len(last['items']) == 5
    assert last['items'][-1]['id'] == 'event-0000'
    assert isinstance(client.get('/v1/security/audit-events').json(), list)


def test_authentication_filter_runs_before_pagination(evidence):
    client, repo = evidence
    for i in range(250):
        add(repo, "security_audit_event", i, action='user.updated', result='success')
    for i in range(30):
        add(repo, "security_audit_event", 300+i, action='auth.login.failed', result='failed')
    page = client.get('/v1/security/auth-events?paginated=true&per_page=20&page=2').json()
    assert page['totalItems'] == 30 and len(page['items']) == 10
    assert all(row['action'].startswith('auth.') for row in page['items'])


def test_snapshot_keeps_pages_stable_when_new_events_arrive(evidence):
    client, repo = evidence
    for i in range(45):
        add(repo, 'security_audit_event', i, action='auth.login.succeeded', result='success')
    first = client.get('/v1/security/audit-events?paginated=true&per_page=20').json()
    cutoff = first['snapshotAt']
    add(repo, 'security_audit_event', 99, created=(datetime.fromisoformat(cutoff)+timedelta(seconds=1)).isoformat(), action='auth.login.failed', result='failed')
    second = client.get('/v1/security/audit-events', params={'paginated':True,'per_page':20,'page':2,'snapshot_at':cutoff}).json()
    assert second['totalItems'] == 45
    assert not ({row['id'] for row in first['items']} & {row['id'] for row in second['items']})
    assert second['items'][0]['id'] == 'event-0024'


def test_search_and_status_filter_cover_old_records_and_spanish_labels(evidence):
    client, repo = evidence
    for i in range(140):
        add(repo, 'security_audit_event', i, action='auth.login.succeeded', result='success', actor_email='common@ucb.edu.bo')
    add(repo, 'security_audit_event', 0, action='auth.login.failed', result='failed', actor_email='old@ucb.edu.bo')
    result = client.get('/v1/security/auth-events?paginated=true&query=old@ucb.edu.bo&status=failed').json()
    assert result['totalItems'] == 1 and result['items'][0]['actor_email'] == 'old@ucb.edu.bo'
    assert client.get('/v1/security/auth-events?paginated=true&query=fallido').json()['totalItems'] == 1


def test_date_filters_use_bolivian_days(evidence):
    client, repo = evidence
    add(repo, 'security_audit_event', 1, created='2026-01-25T01:30:00Z', action='auth.login.succeeded')
    result = client.get('/v1/security/audit-events?paginated=true&date_from=2026-01-24&date_to=2026-01-24').json()
    assert result['totalItems'] == 1
    assert client.get('/v1/security/audit-events?paginated=true&date_from=2026-01-25&date_to=2026-01-25').json()['totalItems'] == 0


def test_summary_counts_entire_dataset_and_excludes_expired_revoked_sessions(evidence):
    client, repo = evidence
    for i in range(230):
        add(repo, 'security_audit_event', i, action='auth.login.failed', result='failed')
    add(repo, 'security_audit_event', 300, action='auth.account.unlocked', result='success')
    for i in range(125):
        add(repo, 'auth_session', i, status='active', expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
    add(repo, 'auth_session', 300, status='active', expires_at=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat())
    add(repo, 'auth_session', 301, status='revoked', expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
    for i,status in enumerate(['open','in_progress','resolved']): add(repo,'security_incident',i,status=status)
    result = client.get('/v1/security/summary').json()
    assert result['counts'] == {'auth':230, 'sessions':125, 'incidents':2}
    assert client.get('/v1/security/sessions?paginated=true&status=expired').json()['totalItems'] == 1


@pytest.mark.parametrize('parameters', ['page=0','per_page=201','status=inventado','date_from=2026-02-01&date_to=2026-01-01','date_to=9999-12-31'])
def test_invalid_paging_and_filters_are_rejected(evidence, parameters):
    client,_=evidence
    assert client.get('/v1/security/audit-events?paginated=true&'+parameters).status_code in (400,422)


def test_permission_is_required_for_each_source_and_summary(evidence):
    client,_=evidence
    app.dependency_overrides[router._get_current_payload]=lambda:{'user_id':'reader','permissions':['revisar_accesos_rbac']}
    assert client.get('/v1/security/access-reviews?paginated=true').status_code == 200
    assert client.get('/v1/security/auth-events?paginated=true').status_code == 403
    assert client.get('/v1/security/summary').status_code == 403


def test_pocketbase_receives_filters_sort_and_requested_page(monkeypatch):
    repo=PocketBaseUserRepository('https://unused.invalid')
    request=Mock(return_value={'items':[], 'totalItems':245})
    monkeypatch.setattr(repo,'_request',request)
    monkeypatch.setattr(repo,'_ensure_authenticated',lambda:None)
    try:
        result=repo.page_security_records('security_audit_event',SecurityQuery(page=13,per_page=20,query='" || id != "',status='failed'))
        params=request.call_args.kwargs['params']
        assert params['page']==13 and params['sort']=='-created,-id'
        assert '\\" || id != \\"' in params['filter']
        assert result['totalPages']==13 and result['snapshotAt']
    finally:repo.close()
