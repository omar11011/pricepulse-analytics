"""Config de tiendas y selectores CSS para scraping."""

from dataclasses import dataclass, field
from typing import Dict, List


# ---
# Selectores CSS
# ---
@dataclass(frozen=True)
class StoreSelectors:
    """Selectores CSS para extraer datos de una tienda."""

    product_card: str = ""
    product_name: str = ""
    product_price: str = ""
    product_price_fraction: str = ""
    product_price_currency: str = ""
    product_url: str = ""
    product_brand: str = ""
    product_image: str = ""
    product_availability: str = ""
    next_page: str = ""
    captcha_indicator: str = ""
    search_results: str = ""
    no_results: str = ""


# ---
# StoreConfig
# ---
@dataclass(frozen=True)
class StoreConfig:
    """Config completa de una tienda para scraping."""

    store_key: str
    store_name: str
    base_url: str
    country: str
    currency: str
    use_playwright: bool
    search_url_template: str
    category_queries: Dict[str, str]
    selectors: StoreSelectors
    delay_min: int = 2
    delay_max: int = 8
    max_pages: int = 2
    timeout: int = 30


# ---
# Mercado Libre
# ---
_mercadolibre_selectors = StoreSelectors(
    product_card="div.ui-search-layout__item, li.ui-search-layout__item",
    product_name="h2.ui-search-item__title, h2.poly-box a",
    product_price="span.andes-money-amount__fraction",
    product_price_fraction="span.andes-money-amount__cents",
    product_price_currency="span.andes-money-amount__currency-symbol",
    product_url="a.ui-search-link, a.poly-component__title",
    product_brand="span.ui-search-item__brand-discoverability-label",
    product_image="img.ui-search-result-image__element",
    product_availability="",
    next_page="a.andes-pagination__link[title='Siguiente']",
    captcha_indicator="div.captcha, form#captcha",
    search_results="section.ui-search-results, ol.ui-search-layout",
    no_results="div.ui-search-message",
)

_mercadolibre_config = StoreConfig(
    store_key="mercadolibre",
    store_name="Mercado Libre",
    base_url="https://listado.mercadolibre.com.mx",
    country="México",
    currency="MXN",
    use_playwright=False,
    search_url_template="https://listado.mercadolibre.com.mx/{query}_Desde_{offset}_NoIndex_True",
    category_queries={
        "CPUs": "procesador cpu",
        "GPUs": "tarjeta grafica gpu",
        "RAM": "memoria ram ddr4 ddr5",
        "SSD": "disco solido ssd",
        "Laptops": "laptop computadora",
        "Monitores": "monitor pantalla",
        "Placas madre": "tarjeta madre motherboard",
    },
    selectors=_mercadolibre_selectors,
    delay_min=3,
    delay_max=7,
    max_pages=2,
    timeout=20,
)


# ---
# AliExpress
# ---
_aliexpress_selectors = StoreSelectors(
    product_card="div.list--galleryWrapper--sgHCSb3, div.search-item",
    product_name="h3.manhattan--titleText--H RSza, a.title",
    product_price="span.manhattan--price-sale--m8RDeI5, span.price-current",
    product_price_fraction="",
    product_price_currency="span.manhattan--currencySymbol--nB4X7fg",
    product_url="a.manhattan--titleLink--K5E2a, a.title",
    product_brand="span.manhattan--brandName--2JCMl6l",
    product_image="img.manhattan--imageImg--2vYg3Wc, img.product-img",
    product_availability="",
    next_page="button.next-btn-next, a.next-pagination-item-next",
    captcha_indicator="div.baxia-dialog, div#nc_1_wrapper",
    search_results="div.list--listContent--nBB2nSI, div.search-content",
    no_results="div.no-result",
)

_aliexpress_config = StoreConfig(
    store_key="aliexpress",
    store_name="AliExpress",
    base_url="https://www.aliexpress.com",
    country="China",
    currency="USD",
    use_playwright=True,
    search_url_template="https://www.aliexpress.com/w/wholesale-{query}.html?page={page}",
    category_queries={
        "CPUs": "cpu processor",
        "GPUs": "graphics card gpu",
        "RAM": "ddr4 ddr5 ram memory",
        "SSD": "ssd solid state drive",
        "Laptops": "laptop notebook",
        "Monitores": "monitor display",
        "Placas madre": "motherboard mainboard",
    },
    selectors=_aliexpress_selectors,
    delay_min=4,
    delay_max=10,
    max_pages=2,
    timeout=30,
)


# ---
# Temu
# ---
_temu_selectors = StoreSelectors(
    product_card="div._2BEOSFr3, div.search-product-card",
    product_name="div._2BEOSFr3 div._2sJSkO2h, a.product-title",
    product_price="span._2sJSkO2h, span.price-current",
    product_price_fraction="",
    product_price_currency="span.currency-symbol",
    product_url="a._2sJSkO2h, a.product-link",
    product_brand="span.brand-name",
    product_image="img._2sJSkO2h, img.product-image",
    product_availability="",
    next_page="button.pagination-next, div._3Uq0cJkG",
    captcha_indicator="div.captcha-verify, div#captcha_verify_container, iframe[src*='captcha']",
    search_results="div.search-results-list, div._2BEOSFr3",
    no_results="div.empty-result",
)

_temu_config = StoreConfig(
    store_key="temu",
    store_name="Temu",
    base_url="https://www.temu.com",
    country="China",
    currency="USD",
    use_playwright=True,
    search_url_template="https://www.temu.com/search_result.html?search_key={query}&page={page}",
    category_queries={
        "CPUs": "cpu processor",
        "GPUs": "graphics card",
        "RAM": "ram memory ddr5",
        "SSD": "ssd storage",
        "Laptops": "laptop computer",
        "Monitores": "computer monitor",
        "Placas madre": "motherboard",
    },
    selectors=_temu_selectors,
    delay_min=5,
    delay_max=12,
    max_pages=1,
    timeout=15,
)


# ---
# Registro de tiendas
# ---
STORE_CONFIGS: Dict[str, StoreConfig] = {
    "mercadolibre": _mercadolibre_config,
    "aliexpress": _aliexpress_config,
    "temu": _temu_config,
}


# ---
# Helpers
# ---
def get_store_config(store_name: str) -> StoreConfig | None:
    """Busca config por nombre de tienda."""
    for config in STORE_CONFIGS.values():
        if config.store_name == store_name:
            return config
    return None


# ---
# Helper: config por clave
# ---
def get_store_config_by_key(store_key: str) -> StoreConfig | None:
    """Busca config por clave interna."""
    return STORE_CONFIGS.get(store_key)


# ---
# Exportación
# ---
__all__ = [
    "StoreSelectors",
    "StoreConfig",
    "STORE_CONFIGS",
    "get_store_config",
    "get_store_config_by_key",
]
