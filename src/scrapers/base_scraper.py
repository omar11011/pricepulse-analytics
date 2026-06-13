"""Base scraper — interfaz común + UA rotation, retries, delays."""

import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from loguru import logger

from src.config import settings
from src.scrapers.scraper_config import StoreConfig, get_store_config_by_key


# ---
# User-Agent pool
# ---
USER_AGENTS: list[str] = [
    # Chrome — Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Chrome — macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    # Firefox — Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    # Firefox — macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:126.0) Gecko/20100101 Firefox/126.0",
    # Edge — Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    # Safari — macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]


def get_random_user_agent() -> str:
    """Retorna un User-Agent aleatorio del pool."""
    return random.choice(USER_AGENTS)


# ---
# ScrapeResult
# ---
@dataclass
class ScrapeResult:
    """Resultado estandarizado de scraping — todos los scrapers retornan esto."""

    name: str
    brand: str | None
    price: float
    currency: str
    availability: bool
    url: str
    sku: str | None = None
    store_name: str = ""
    category: str = ""
    scraped_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> dict[str, Any]:
        """Convierte a dict para Pandas."""
        return {
            "name": self.name,
            "brand": self.brand,
            "price": self.price,
            "currency": self.currency,
            "availability": self.availability,
            "url": self.url,
            "sku": self.sku,
            "store_name": self.store_name,
            "category": self.category,
            "scraped_at": self.scraped_at,
        }


# ---
# BaseScraper
# ---
class BaseScraper(ABC):
    """Scraper base — UA rotation, delays, retries, normalización. Subclases implementan get_products() y get_price()."""

    def __init__(self, store_key: str) -> None:
        self._store_key = store_key
        self._config: StoreConfig | None = get_store_config_by_key(store_key)

        if self._config is None:
            raise ValueError(
                f"Configuración no encontrada para store_key='{store_key}'. "
                f"Claves disponibles: {list(STORE_CONFIGS.keys())}"
            )

        # Contadores de métricas
        self._products_found: int = 0
        self._products_saved: int = 0
        self._products_failed: int = 0
        self._captcha_detected: int = 0

        logger.info(
            f"Scraper inicializado: {self._config.store_name} "
            f"(playwright={self._config.use_playwright}, "
            f"currency={self._config.currency})"
        )

    # ---
    # Propiedades
    # ---
    @property
    def store_name(self) -> str:
        """Nombre de la tienda."""
        return self._config.store_name if self._config else ""

    @property
    def config(self) -> StoreConfig:
        """Config de la tienda."""
        assert self._config is not None, "StoreConfig no inicializada"
        return self._config

    @property
    def stats(self) -> dict[str, int]:
        """Stats de la última ejecución."""
        return {
            "products_found": self._products_found,
            "products_saved": self._products_saved,
            "products_failed": self._products_failed,
            "captcha_detected": self._captcha_detected,
        }

    # ---
    # Métodos abstractos
    # ---
    @abstractmethod
    def get_products(self, category: str) -> list[ScrapeResult]:
        """Extrae listado de productos para una categoría."""
        ...

    @abstractmethod
    def get_price(self, product_url: str) -> dict[str, Any] | None:
        """Extrae el precio de un producto específico."""
        ...

    # ---
    # Métodos concretos
    # ---
    def _normalize_name(self, name: str) -> str:
        """Normaliza nombre: strip, colapsar espacios, eliminar ctrl chars, truncar 300."""
        if not name:
            return ""

        normalized = name.strip()
        # Colapsar múltiples espacios/tabs/newlines
        normalized = " ".join(normalized.split())
        # Eliminar caracteres de control (excepto espacios)
        normalized = "".join(c for c in normalized if ord(c) >= 32 or c == " ")
        # Primera letra mayúscula
        if normalized:
            normalized = normalized[0].upper() + normalized[1:]
        # Truncar al límite de BD
        if len(normalized) > 300:
            normalized = normalized[:297] + "..."

        return normalized

    def _detect_changes(self, current_html: str, previous_html: str) -> bool:
        """Detecta si cambió el HTML comparando longitud + hash (>10% diff = cambio)."""
        if not previous_html:
            return False  # No hay referencia anterior

        len_current = len(current_html)
        len_previous = len(previous_html)

        # Diferencia de longitud mayor al 10%
        if len_previous > 0:
            diff_pct = abs(len_current - len_previous) / len_previous
            if diff_pct > 0.10:
                logger.warning(
                    f"Cambio detectado en estructura HTML de {self.store_name}: "
                    f"variación de longitud {diff_pct:.1%}"
                )
                return True

        return False

    def _delay(self) -> None:
        """Delay aleatorio entre requests — no sobrecargar servidores."""
        min_delay = self.config.delay_min
        max_delay = self.config.delay_max
        delay = random.uniform(min_delay, max_delay)
        logger.debug(f"Delay: {delay:.1f}s ({self.store_name})")
        time.sleep(delay)

    def _get_headers(self) -> dict[str, str]:
        """Headers HTTP con User-Agent rotado."""
        return {
            "User-Agent": get_random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

    def _retry_request(
        self,
        request_fn: Callable[..., Any],
        max_retries: int | None = None,
        retry_delay: int | None = None,
    ) -> Any:
        """Ejecuta fn con reintentos y backoff exponencial."""
        if max_retries is None:
            max_retries = settings.scrape.max_retries
        if retry_delay is None:
            retry_delay = settings.scrape.retry_delay

        last_exception: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                return request_fn()
            except Exception as e:
                last_exception = e
                wait_time = retry_delay * (2 ** (attempt - 1))
                logger.warning(
                    f"Intento {attempt}/{max_retries} fallido para {self.store_name}: "
                    f"{type(e).__name__}: {e}. Reintentando en {wait_time}s..."
                )
                time.sleep(wait_time)

        logger.error(
            f"Todos los reintentos agotados para {self.store_name}: "
            f"{type(last_exception).__name__}: {last_exception}"
        )
        self._products_failed += 1
        return None

    def _parse_price(self, price_text: str) -> float | None:
        """Parsea texto de precio a float (maneja formatos MX y US)."""
        if not price_text:
            return None

        # Limpiar: eliminar símbolos de moneda y espacios
        # Ordenar de más largo a más corto para evitar reemplazos parciales
        # (ej: "US$" debe eliminarse antes que "$")
        cleaned = price_text.strip()
        for symbol in ["US$", "MX$", "USD", "MXN", "$", "€", "¥"]:
            cleaned = cleaned.replace(symbol, "")
        cleaned = cleaned.strip()

        if not cleaned:
            return None

        # Detectar formato: europeo (1.234,56) vs americano (1,234.56)
        has_comma = "," in cleaned
        has_dot = "." in cleaned

        if has_comma and has_dot:
            comma_pos = cleaned.rfind(",")
            dot_pos = cleaned.rfind(".")
            if comma_pos > dot_pos:
                # Formato europeo: 1.234,56 → 1234.56
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                # Formato americano: 1,234.56 → 1234.56
                cleaned = cleaned.replace(",", "")
        elif has_comma:
            # Solo coma: decidir si es decimal o separador de miles
            parts = cleaned.split(",")
            if len(parts) == 2 and len(parts[1]) <= 2:
                # Probablemente decimal: 123,45 → 123.45
                cleaned = cleaned.replace(",", ".")
            else:
                # Probablemente separador de miles: 1,234 → 1234
                cleaned = cleaned.replace(",", "")
        # Si solo tiene punto, ya está en formato correcto

        try:
            price = float(cleaned)
            # Validación básica: precio negativo o cero es sospechoso
            if price <= 0:
                logger.warning(f"Precio sospechoso: {price} (original: '{price_text}')")
                return None
            return price
        except ValueError:
            logger.warning(f"No se pudo parsear precio: '{price_text}' → '{cleaned}'")
            return None

    def reset_stats(self) -> None:
        """Reinicia contadores."""
        self._products_found = 0
        self._products_saved = 0
        self._products_failed = 0
        self._captcha_detected = 0

    def _build_search_url(self, category: str, page: int = 1) -> str:
        """Construye URL de búsqueda para categoría + página."""
        query = self.config.category_queries.get(category, category.lower())
        offset = (page - 1) * 48 + 1  # ML usa offset 1-based

        url = self.config.search_url_template.format(
            query=query.replace(" ", "-"),
            page=page,
            offset=offset,
        )
        return url


# ---
# Exportación
# ---
__all__ = [
    "BaseScraper",
    "ScrapeResult",
    "USER_AGENTS",
    "get_random_user_agent",
]
