from app.infrastructure.pocketbase_client import PocketBaseClient


def test_runtime_schema_update_preserves_demo_fields_and_field_ids():
    client = object.__new__(PocketBaseClient)
    client._base_url = 'http://pocketbase'
    client.get_collection = lambda _: {'id': 'history', 'fields': [
        {'id': 'date_id', 'name': 'executed_at', 'type': 'date'},
        {'id': 'demo_id', 'name': 'demo_dataset', 'type': 'text', 'max': 80},
    ]}
    requests = []
    client._request = lambda *args, **kwargs: requests.append((args, kwargs))
    client.ensure_collection('history', [{'name': 'executed_at', 'type': 'date', 'required': True}])
    fields = {field['name']: field for field in requests[0][1]['json']['fields']}
    assert fields['executed_at']['id'] == 'date_id'
    assert fields['executed_at']['required'] is True
    assert fields['demo_dataset']['id'] == 'demo_id'
