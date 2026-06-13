"""Config centralizada: carga .env y expone constantes tipadas."""

import os
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv

_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
_env_file: Path = _PROJECT_ROOT / ".env"

if _env_file.exists():
    load_dotenv(_env_file)
else:
    load_dotenv()


def _get_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _get_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _get_str(key: str, default: str = "") -> str:
    return os.getenv(key, default)


@dataclass(frozen=True)
class DatabaseSettings:
    url_override: str = field(
        default_factory=lambda: _get_str("DATABASE_URL", "")
    )
    host: str = field(default_factory=lambda: _get_str("DB_HOST", "localhost"))
    port: int = field(default_factory=lambda: _get_int("DB_PORT", 5432))
    name: str = field(default_factory=lambda: _get_str("DB_NAME", "pricepulse"))
    user: str = field(default_factory=lambda: _get_str("DB_USER", "pricepulse_user"))
    password: str = field(default_factory=lambda: _get_str("DB_PASSWORD", ""))

    @property
    def is_sqlite(self) -> bool:
        return self._resolved_url.startswith("sqlite")

    @property
    def is_postgresql(self) -> bool:
        return self._resolved_url.startswith("postgresql")

    @property
    def dialect_name(self) -> str:
        if self.is_sqlite:
            return "sqlite"
        return "postgresql"

    @property
    def _resolved_url(self) -> str:
        if self.url_override:
            raw = self.url_override
            if raw.startswith("file:"):
                path = raw[len("file:"):]
                return f"sqlite:///{path}"
            return raw
        if self.user and self.host != "localhost":
            return (
                f"postgresql+psycopg2://{self.user}:{self.password}"
                f"@{self.host}:{self.port}/{self.name}"
            )
        return f"sqlite:///{_PROJECT_ROOT / 'data' / 'pricepulse.db'}"

    @property
    def url(self) -> str:
        raw_url = self._resolved_url
        if raw_url.startswith("sqlite:///") and not raw_url.startswith("sqlite:////"):
            relative_path = raw_url[len("sqlite:///"):]
            if not os.path.isabs(relative_path):
                abs_path = _PROJECT_ROOT / relative_path
                return f"sqlite:///{abs_path}"
        return raw_url

    @property
    def url_async(self) -> str:
        if self.is_sqlite:
            raw = self.url
            return raw.replace("sqlite:///", "sqlite+aiosqlite:///")
        return (
            f"postgresql+asyncpg://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )


@dataclass(frozen=True)
class ScrapeSettings:
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
    usd_to_mxn: float = field(
        default_factory=lambda: _get_float("USD_TO_MXN_RATE", 17.50)
    )
    base_currency: str = "MXN"


@dataclass(frozen=True)
class AppSettings:
    log_level: str = field(default_factory=lambda: _get_str("LOG_LEVEL", "INFO"))
    project_root: Path = field(default_factory=lambda: _PROJECT_ROOT)


@dataclass(frozen=True)
class Settings:
    database: DatabaseSettings = field(default_factory=DatabaseSettings)
    scrape: ScrapeSettings = field(default_factory=ScrapeSettings)
    currency: CurrencySettings = field(default_factory=CurrencySettings)
    app: AppSettings = field(default_factory=AppSettings)


settings: Settings = Settings()


class Categories:
    CPU: str = "CPUs"
    GPU: str = "GPUs"
    RAM: str = "RAM"
    SSD: str = "SSD"
    LAPTOP: str = "Laptops"
    MONITOR: str = "Monitores"
    MOTHERBOARD: str = "Placas madre"

    ALL: list[str] = [CPU, GPU, RAM, SSD, LAPTOP, MONITOR, MOTHERBOARD]


class Stores:
    MERCADO_LIBRE: str = "Mercado Libre"
    ALIEXPRESS: str = "AliExpress"
    TEMU: str = "Temu"

    ALL: list[str] = [MERCADO_LIBRE, ALIEXPRESS, TEMU]


class PriceValidation:
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
        price_range = cls.RANGES.get(category)
        if price_range is None:
            return True
        return price_range[0] <= price <= price_range[1]


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