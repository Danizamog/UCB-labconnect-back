from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.v1.endpoints import assets, loans, asset_maintenance, equipment_requests, reports
from app.core.dependencies import get_current_user


@pytest.fixture
def isolated(monkeypatch):
    app = FastAPI()
    for module in [assets, loans, asset_maintenance, equipment_requests, reports]:
        app.include_router(module.router)
        if hasattr(module, 'resolve_accessible_lab_ids'):
            monkeypatch.setattr(module, 'resolve_accessible_lab_ids', lambda _: ['lab-1'])
    monkeypatch.setattr(assets, 'asset_repo', SimpleNamespace(list_all=lambda: [], get_by_id=lambda _: None))
    monkeypatch.setattr(asset_maintenance, 'asset_maintenance_repo', SimpleNamespace(list_all=lambda **_: [], get_by_id=lambda _: None))
    monkeypatch.setattr(loans, 'loan_record_repo', SimpleNamespace(list_paginated=lambda **_: {'items':[], 'page':1,'per_page':50,'total_items':0,'total_pages':0}))
    monkeypatch.setattr(equipment_requests, 'equipment_request_repo', SimpleNamespace(list_all=lambda **_: [], get_by_id=lambda _: None))
    actor = {'user_id':'operator','role':'Administrador','permissions':[]}
    app.dependency_overrides[get_current_user] = lambda: actor
    return TestClient(app), actor


@pytest.mark.parametrize('permission', ['gestionar_inventario','gestionar_estado_equipos','gestionar_mantenimiento','registrar_tickets_equipo','gestionar_prestamos'])
def test_single_permission_loads_auxiliary_assets_without_unrelated_mutations(isolated, permission):
    client, actor = isolated
    actor['permissions'] = [permission]
    assert client.get('/assets').status_code == 200
    assert client.get('/loans').status_code == (200 if permission == 'gestionar_prestamos' else 403)
    assert client.get('/asset-maintenance').status_code == (200 if permission in {'gestionar_mantenimiento','registrar_tickets_equipo'} else 403)
    assert client.patch('/assets/missing/status', json={'status':'available'}).status_code == (404 if permission == 'gestionar_estado_equipos' else 403)
    assert client.patch('/asset-maintenance/tickets/missing/close', json={'resolution_notes':'Reparado'}).status_code == (404 if permission == 'gestionar_mantenimiento' else 403)


@pytest.mark.parametrize('permission', ['gestionar_stock','gestionar_reactivos_quimicos','gestionar_inventario'])
def test_operational_permissions_do_not_grant_report_access(isolated, permission):
    client, actor = isolated
    actor['permissions'] = [permission]
    assert client.get('/reports/usage').status_code == 403
    assert client.get('/reports/stock-items').status_code == 403


def test_scope_is_applied_to_reports(monkeypatch):
    actor = {'permissions':['generar_reportes']}
    repo = Mock()
    repo.list_all.return_value = []
    monkeypatch.setattr(reports,'loan_record_repo',repo)
    monkeypatch.setattr(reports,'resolve_accessible_lab_ids',lambda _: ['lab-1'])
    reports.get_usage_report(borrower_id=None,practice=None,date_from=None,date_to=None,current_user=actor)
    repo.list_all.assert_called_once_with(lab_ids=['lab-1'])
