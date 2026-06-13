"""
Módulo de Extracción (Scrapers).

Responsabilidades:
    - Obtener listados de productos desde tiendas online
    - Extraer nombre, marca, precio, disponibilidad y URL
    - Manejar errores de red, CAPTCHAs y cambios de estructura
    - Registrar logs de cada operación de scraping

Tiendas soportadas:
    - Mercado Libre México
    - AliExpress
    - Temu

Uso rápido:
    from src.scrapers import BaseScraper, ScrapeResult, STORE_CONFIGS
    from src.scrapers.base_scraper import get_random_user_agent

    config = STORE_CONFIGS["mercadolibre"]
    print(config.base_url)
    print(config.selectors.product_name)
"""

from src.scrapers.base_scraper import (
    BaseScraper,
    ScrapeResult,
    USER_AGENTS,
    get_random_user_agent,
)
from src.scrapers.scraper_config import (
    StoreSelectors,
    StoreConfig,
    STORE_CONFIGS,
    get_store_config,
    get_store_config_by_key,
)
from src.scrapers.mercadolibre_scraper import MercadoLibreScraper
from src.scrapers.aliexpress_scraper import AliExpressScraper
from src.scrapers.temu_scraper import TemuScraper

__all__ = [
    # Base
    "BaseScraper",
    "ScrapeResult",
    "USER_AGENTS",
    "get_random_user_agent",
    # Config
    "StoreSelectors",
    "StoreConfig",
    "STORE_CONFIGS",
    "get_store_config",
    "get_store_config_by_key",
    # Scrapers
    "MercadoLibreScraper",
    "AliExpressScraper",
    "TemuScraper",
]
