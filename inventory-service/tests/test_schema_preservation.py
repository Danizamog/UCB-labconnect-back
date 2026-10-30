from app.infrastructure.pocketbase_client import PocketBaseClient


def test_runtime_schema_update_preserves_existing_fields_ids_and_metadata():
    client = object.__new__(PocketBaseClient)
    client._base_url = 'http://pocketbase'
    client.get_collection = lambda _: {'id': 'collection', 'fields': [
        {'id': 'stable_id', 'name': 'name', 'type': 'text', 'max': 20},
        {'id': 'demo_flag', 'name': 'is_demo', 'type': 'bool'},
        {'id': 'audit_date', 'name': 'created', 'type': 'autodate', 'onCreate': True},
    ]}
    requests = []
    client._request = lambda *args, **kwargs: requests.append((args, kwargs))
    client.ensure_collection('example', [{'name': 'name', 'type': 'text', 'max': 40}])
    fields = {field['name']: field for field in requests[0][1]['json']['fields']}
    assert fields['name']['id'] == 'stable_id'
    assert fields['name']['max'] == 40
    assert fields['is_demo']['id'] == 'demo_flag'
    assert fields['created']['onCreate'] is True
    assert set(requests[0][1]['json']) == {'fields'}
