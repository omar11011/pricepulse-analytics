"""Conexión a BD — SessionFactory singleton, context manager, init_db."""

import os
from contextlib import contextmanager
from typing import Generator

from loguru import logger
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.config import settings
from src.database.models import Base


# ---
# SessionFactory — Singleton perezoso
# ---
class SessionFactory:
    """Factory de sesiones SQLAlchemy (singleton, lazy init)."""

    _engine: Engine | None = None
    _session_factory: sessionmaker | None = None

    @classmethod
    def get_engine(cls) -> Engine:
        """Crea o retorna la engine SQLAlchemy (lazy)."""
        if cls._engine is None:
            db_url = settings.database.url
            is_sqlite = settings.database.is_sqlite

            # Log seguro (ocultar passwords en PostgreSQL)
            if is_sqlite:
                safe_url = db_url
            else:
                safe_url = db_url.split("@")[-1] if "@" in db_url else db_url

            logger.info(
                f"Creando engine SQLAlchemy → [{settings.database.dialect_name}] {safe_url}"
            )

            if is_sqlite:
                # ── SQLite ──
                # Asegurar que el directorio del archivo DB existe
                db_path = db_url.replace("sqlite:///", "")
                db_dir = os.path.dirname(db_path)
                if db_dir and not os.path.exists(db_dir):
                    os.makedirs(db_dir, exist_ok=True)
                    logger.info(f"Directorio de BD creado: {db_dir}")

                cls._engine = create_engine(
                    db_url,
                    echo=(settings.app.log_level == "DEBUG"),
                )

                # Habilitar WAL mode y foreign keys en SQLite
                @event.listens_for(cls._engine, "connect")
                def _set_sqlite_pragma(dbapi_conn, connection_record) -> None:  # type: ignore[no-untyped-def]
                    cursor = dbapi_conn.cursor()
                    # WAL mode: permite lecturas concurrentes mientras se escribe
                    cursor.execute("PRAGMA journal_mode=WAL")
                    # Foreign keys: SQLite no las activa por defecto
                    cursor.execute("PRAGMA foreign_keys=ON")
                    # Busy timeout: esperar hasta 5s si la BD está bloqueada
                    cursor.execute("PRAGMA busy_timeout=5000")
                    cursor.close()
                    logger.debug("SQLite pragmas configurados (WAL, FK, busy_timeout)")

                logger.info("SQLite engine creada — modo WAL, foreign keys activas")

            else:
                # ── PostgreSQL ──
                cls._engine = create_engine(
                    db_url,
                    pool_pre_ping=True,
                    pool_size=5,
                    max_overflow=10,
                    echo=(settings.app.log_level == "DEBUG"),
                )

                @event.listens_for(cls._engine, "connect")
                def _on_connect(dbapi_conn, connection_record) -> None:  # type: ignore[no-untyped-def]
                    logger.debug("Nueva conexión a PostgreSQL establecida")

        return cls._engine

    @classmethod
    def get_session_factory(cls) -> sessionmaker:
        """Crea o retorna el sessionmaker."""
        if cls._session_factory is None:
            cls._session_factory = sessionmaker(
                bind=cls.get_engine(),
                autocommit=False,
                autoflush=False,
                expire_on_commit=True,
            )
        return cls._session_factory

    @classmethod
    def reset(cls) -> None:
        """Cierra engine y resetea factory (útil para tests)."""
        if cls._engine is not None:
            cls._engine.dispose()
            logger.info("Engine SQLAlchemy cerrada")
        cls._engine = None
        cls._session_factory = None


# ---
# Context manager
# ---
@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Sesión con commit/rollback automático. Si hay excepción → rollback."""
    session_factory = SessionFactory.get_session_factory()
    session = session_factory()

    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Error en sesión de BD — rollback ejecutado")
        raise
    finally:
        session.close()


# ---
# Inicialización BD
# ---
def init_db() -> None:
    """Crea todas las tablas si no existen (idempotente)."""
    engine = SessionFactory.get_engine()
    dialect = settings.database.dialect_name.upper()

    logger.info(f"Inicializando tablas en {dialect}...")

    Base.metadata.create_all(bind=engine)

    logger.info(f"Tablas creadas/verificadas exitosamente en {dialect}")


def check_connection() -> bool:
    """Chequeo de conectividad — ejecuta SELECT 1. Útil para health checks."""
    dialect = settings.database.dialect_name.upper()
    try:
        engine = SessionFactory.get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info(f"Conexión a {dialect} verificada")
        return True
    except Exception as e:
        logger.error(f"Error de conexión a {dialect}: {e}")
        return False


# ---
# Exportación
# ---
__all__ = [
    "SessionFactory",
    "get_session",
    "init_db",
    "check_connection",
]
