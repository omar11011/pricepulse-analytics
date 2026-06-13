"""Conexion a BD — soporta SQLite y PostgreSQL."""

from contextlib import contextmanager
from pathlib import Path

from loguru import logger
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from src.config import settings


_engine = None
_session_factory = None


def get_engine():
    global _engine, _session_factory
    if _engine is not None:
        return _engine

    url = settings.database.url
    logger.info(f"Creando engine SQLAlchemy → [{settings.database.dialect_name}] {url}")

    # crear directorio para SQLite si no existe
    if settings.database.is_sqlite:
        db_path = url.replace("sqlite:///", "")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    connect_args = {}
    engine_kwargs = {}

    if settings.database.is_sqlite:
        connect_args["check_same_thread"] = False
        engine_kwargs["connect_args"] = connect_args
        engine_kwargs["pool_pre_ping"] = True
    else:
        engine_kwargs["pool_pre_ping"] = True
        engine_kwargs["pool_size"] = 5
        engine_kwargs["max_overflow"] = 10

    _engine = create_engine(url, **engine_kwargs)

    if settings.database.is_sqlite:
        event.listen(_engine, "connect", _set_sqlite_pragma)

    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    logger.info(f"Engine creada — {_engine.url}")
    return _engine


def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()
    logger.debug("SQLite pragmas configurados (WAL, FK, busy_timeout)")


@contextmanager
def get_session():
    if _session_factory is None:
        get_engine()
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db():
    from src.database.models import Base
    engine = get_engine()
    Base.metadata.create_all(engine)
    logger.info(f"Tablas creadas/verificadas en {settings.database.dialect_name.upper()}")


def check_connection() -> bool:
    try:
        with get_session() as session:
            session.execute(text("SELECT 1"))
        logger.info(f"Conexion a {settings.database.dialect_name.upper()} verificada")
        return True
    except Exception as e:
        logger.error(f"Error de conexion: {e}")
        return False