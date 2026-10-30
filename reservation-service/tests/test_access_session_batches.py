from types import SimpleNamespace
from unittest.mock import Mock

from app.infrastructure.repositories.lab_access_session_repository import LabAccessSessionRepository


def test_large_reservation_lists_use_bounded_filters():
    repo=object.__new__(LabAccessSessionRepository)
    repo._ensure_collection=lambda:None
    repo._collection='access_sessions'
    fetch=Mock(return_value=[])
    repo._client=SimpleNamespace(list_records=fetch)
    ids=[f'user{i:011d}' for i in range(135)]
    assert repo.list_by_reservation_ids(ids+ids[:5])==[]
    assert fetch.call_count==7
    for call in fetch.call_args_list:
        assert call.kwargs['filter'].count('reservation_id=')<=20
