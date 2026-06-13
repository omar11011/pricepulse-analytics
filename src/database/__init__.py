"""
Módulo de Base de Datos.

Responsabilidades:
    - Definir modelos ORM con SQLAlchemy
    - Gestionar conexiones a base de datos (SQLite o PostgreSQL)
    - Proveer context managers para sesiones seguras
    - Inicializar tablas e índices

Motores soportados:
    - SQLite: desarrollo local, Vercel, Streamlit Cloud (default)
    - PostgreSQL: producción en VPS con alta concurrencia

Tablas:
    - stores:         Tiendas monitoreadas
    - categories:     Categorías de productos
    - products:       Productos detectados
    - price_history:  Historial de precios
    - pipeline_logs:  Registro de ejecuciones del pipeline

Uso rápido:
    from src.database import get_session, init_db, Product, Store

    init_db()

    with get_session() as session:
        products = session.query(Product).all()
"""

from src.database.models import (
    Base,
    Store,
    Category,
    Product,
    PriceHistory,
    PipelineLog,
)
from src.database.connection import (
    SessionFactory,
    get_session,
    init_db,
    check_connection,
)

__all__ = [
    # Modelos
    "Base",
    "Store",
    "Category",
    "Product",
    "PriceHistory",
    "PipelineLog",
    # Conexión
    "SessionFactory",
    "get_session",
    "init_db",
    "check_connection",
]
