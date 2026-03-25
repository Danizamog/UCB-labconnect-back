from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


engine_kwargs: dict = {"pool_pre_ping": True, "future": True}

if settings.database_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {
        "check_same_thread": False,
        "timeout": 30,
    }

engine = create_engine(settings.database_url, **engine_kwargs)


@event.listens_for(Engine, "connect")
def configure_sqlite_connection(dbapi_connection, connection_record) -> None:  # noqa: ARG001
    database_name = dbapi_connection.__class__.__module__.split(".", maxsplit=1)[0]
    if database_name != "sqlite3":
        return

    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.execute("PRAGMA busy_timeout=30000;")
    cursor.close()


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True,
)
