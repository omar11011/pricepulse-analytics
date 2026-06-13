"""Config centralizada: carga .env y expone constantes tipadas."""

import os
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv

# ---
# Cargar .env
# ---
_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
_env_file: Path = _PROJECT_ROOT / ".env"

if _env_file.exists():
    load_dotenv(_env_file)
else:
    # En Docker o CI, las variables pueden venir inyectadas directamente
    load_dotenv()


# ---
# Helpers
# ---
def _get_int(key: str, default: int) -> int:
    """Lee env var como int, con fallback."""
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _get_float(key: str, default: float) -> float:
    """Lee env var como float, con fallback."""
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _get_str(key: str, default: str = "") -> str:
    """Lee env var como string, con fallback."""
    return os.getenv(key, default)


# ---
# Settings
# ---
@dataclass(frozen=True)
class DatabaseSettings:
    """Config de BD — SQLite para dev, PostgreSQL para prod."""

    # DATABASE_URL tiene prioridad sobre las variables individuales
    url_override: str = field(
        default_factory=lambda: _get_str("DATABASE_URL", "")
    )

    # Fallback PostgreSQL si no hay DATABASE_URL
    host: str = field(default_factory=lambda: _get_str("DB_HOST", "localhost"))
    port: int = field(default_factory=lambda: _get_int("DB_PORT", 5432))
    name: str = field(default_factory=lambda: _get_str("DB_NAME", "pricepulse"))
    user: str = field(default_factory=lambda: _get_str("DB_USER", "pricepulse_user"))
    password: str = field(default_factory=lambda: _get_str("DB_PASSWORD", ""))

    @property
    def is_sqlite(self) -> bool:
        """¿Es SQLite?"""
        url = self._resolved_url
        return url.startswith("sqlite")

    @property
    def is_postgresql(self) -> bool:
        """¿Es PostgreSQL?"""
        url = self._resolved_url
        return url.startswith("postgresql")

    @property
    def dialect_name(self) -> str:
        """'sqlite' o 'postgresql'."""
        if self.is_sqlite:
            return "sqlite"
        return "postgresql"

    @property
    def _resolved_url(self) -> str:
        """Resuelve la URL final (DATABASE_URL o construida desde vars)."""
        if self.url_override:
            raw = self.url_override
            # Convertir formato file: (no-SQLAlchemy) a sqlite:/// (SQLAlchemy)
            if raw.startswith("file:"):
                path = raw[len("file:"):]
                # file:/path → sqlite:////path (absoluta con 4 barras)
                return f"sqlite:///{path}"
            return raw
        # Sin DATABASE_URL → construir URL PostgreSQL desde variables individuales
        return (
            f"postgresql+psycopg2://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )

    @property
    def url(self) -> str:
        """URL SQLAlchemy síncrona — normaliza rutas SQLite relativas al proyecto."""
        raw_url = self._resolved_url

        # Normalizar rutas SQLite relativas al proyecto
        if raw_url.startswith("sqlite:///") and not raw_url.startswith("sqlite:////"):
            # sqlite:///path → relativa al CWD
            # Convertimos a absoluta basada en el root del proyecto
            relative_path = raw_url[len("sqlite:///"):]
            if not os.path.isabs(relative_path):
                abs_path = _PROJECT_ROOT / relative_path
                return f"sqlite:///{abs_path}"

        return raw_url

    @property
    def url_async(self) -> str:
        """URL async (para FastAPI futuro) — PostgreSQL usa asyncpg, SQLite usa aiosqlite."""
        if self.is_sqlite:
            # SQLite async requiere aiosqlite
            raw = self.url
            return raw.replace("sqlite:///", "sqlite+aiosqlite:///")
        return (
            f"postgresql+asyncpg://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )


@dataclass(frozen=True)
class ScrapeSettings:
    """Config del scraper."""

    delay_min: int = field(default_factory=lambda: _get_int("SCRAPE_DELAY_MIN", 2))
    delay_max: int = field(default_factory=lambda: _get_int("SCRAPE_DELAY_MAX", 8))
    max_retries: int = field(default_factory=lambda: _get_int("SCRAPE_MAX_RETRIES", 3))
    retry_delay: int = field(default_factory=lambda: _get_int("SCRAPE_RETRY_DELAY", 5))
    products_per_category: int = field(
        default_factory=lambda: _get_int("SCRAPE_PRODUCTS_PER_CATEGORY", 20)
    )
    max_pages: int = field(default_factory=lambda: _get_int("SCRAPE_MAX_PAGES", 2))


@dataclass(frozen=True)
class CurrencySettings:
    """Config de conversión de monedas."""

    usd_to_mxn: float = field(
        default_factory=lambda: _get_float("USD_TO_MXN_RATE", 17.50)
    )
    base_currency: str = "MXN"


@dataclass(frozen=True)
class AppSettings:
    """Config general de la app."""

    log_level: str = field(default_factory=lambda: _get_str("LOG_LEVEL", "INFO"))
    project_root: Path = field(default_factory=lambda: _PROJECT_ROOT)


# ---
# Instancia singleton
# ---
@dataclass(frozen=True)
class Settings:
    """Config global — importa `settings` y ya."""

    database: DatabaseSettings = field(default_factory=DatabaseSettings)
    scrape: ScrapeSettings = field(default_factory=ScrapeSettings)
    currency: CurrencySettings = field(default_factory=CurrencySettings)
    app: AppSettings = field(default_factory=AppSettings)


# Instancia global — inmutable, se importa desde cualquier módulo
settings: Settings = Settings()


# ---
# Constantes de negocio
# ---
class Categories:
    """Categorías que monitoreamos."""

    CPU: str = "CPUs"
    GPU: str = "GPUs"
    RAM: str = "RAM"
    SSD: str = "SSD"
    LAPTOP: str = "Laptops"
    MONITOR: str = "Monitores"
    MOTHERBOARD: str = "Placas madre"

    ALL: list[str] = [CPU, GPU, RAM, SSD, LAPTOP, MONITOR, MOTHERBOARD]


class Stores:
    """Tiendas que monitoreamos."""

    MERCADO_LIBRE: str = "Mercado Libre"
    ALIEXPRESS: str = "AliExpress"
    TEMU: str = "Temu"

    ALL: list[str] = [MERCADO_LIBRE, ALIEXPRESS, TEMU]


class PriceValidation:
    """Rangos de precio por categoría — fuera de rango = sospechoso."""

    RANGES: dict[str, tuple[float, float]] = {
        Categories.CPU: (500.0, 35_000.0),
        Categories.GPU: (1_000.0, 60_000.0),
        Categories.RAM: (200.0, 15_000.0),
        Categories.SSD: (300.0, 12_000.0),
        Categories.LAPTOP: (5_000.0, 80_000.0),
        Categories.MONITOR: (1_500.0, 50_000.0),
        Categories.MOTHERBOARD: (800.0, 20_000.0),
    }

    @classmethod
    def is_valid_price(cls, category: str, price: float) -> bool:
        """¿Precio dentro del rango esperado?"""
        price_range = cls.RANGES.get(category)
        if price_range is None:
            return True  # Sin rango definido, no validamos
        return price_range[0] <= price <= price_range[1]


# ---
# Exportación
# ---
__all__ = [
    "settings",
    "Settings",
    "DatabaseSettings",
    "ScrapeSettings",
    "CurrencySettings",
    "AppSettings",
    "Categories",
    "Stores",
    "PriceValidation",
]
