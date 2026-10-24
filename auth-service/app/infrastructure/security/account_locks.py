from contextlib import contextmanager
from threading import Lock

_guard = Lock()
_locks: dict[str, tuple[Lock, int]] = {}


@contextmanager
def account_login_lock(username: str):
    with _guard:
        entry, count = _locks.get(username, (Lock(), 0))
        _locks[username] = (entry, count + 1)
    try:
        with entry:
            yield
    finally:
        with _guard:
            _, count = _locks[username]
            if count == 1:
                del _locks[username]
            else:
                _locks[username] = (entry, count - 1)
