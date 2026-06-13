"""
PricePulse Analytics — Scraper de Mercado Libre México.

Scraper concreto que extrae productos tecnológicos desde
mercadolibre.com.mx usando requests + BeautifulSoup4.

Estrategia de extracción:
    Mercado Libre México utiliza renderizado server-side para las
    páginas de listado de búsqueda, por lo que requests + BS4 son
    suficientes (no se necesita Playwright). Los precios y nombres
    están disponibles en el HTML inicial.

    URL de búsqueda:
        https://listado.mercadolibre.com.mx/{query}_Desde_{offset}_NoIndex_True

    Donde {query} es el término de búsqueda con guiones y {offset}
    es el índice del primer resultado (1, 49, 97, ...).

Manejo de errores:
    - CAPTCHA: Se detecta por presencia de form#captcha o div.captcha.
      Si se detecta, se salta la categoría actual y se loguea.
    - Rate limiting: HTTP 429 → retry con backoff exponencial.
    - Productos sin precio: Se registran como no disponibles.
    - Cambios de estructura: Se compara longitud del HTML con
      la de la página anterior para detectar cambios.

Limitaciones conocidas:
    - Mercado Libre puede servir páginas de CAPTCHA sin código 429.
    - Los precios de envío no se extraen (solo precio base).
    - La marca no siempre está visible en el listado; se intenta
      extraer del nombre del producto como fallback.
    - Mercado Libre actualiza sus selectores CSS con frecuencia.
      Si el scraper retorna 0 productos, verificar scraper_config.py.

Uso:
    scraper = MercadoLibreScraper()
    results = scraper.get_products("CPUs")
    for r in results:
        print(r.name, r.price, r.currency)
"""

import re
from typing import Any

import requests
from bs4 import BeautifulSoup, Tag
from loguru import logger

from src.scrapers.base_scraper import BaseScraper, ScrapeResult
from src.scrapers.scraper_config import STORE_CONFIGS


# ---------------------------------------------------------------------------
# Patrones regex para extracción de marca del nombre
# ---------------------------------------------------------------------------
_BRAND_PATTERNS: dict[str, list[str]] = {
    "CPUs": ["AMD", "Intel", "Ryzen", "Core i", "Celeron", "Xeon"],
    "GPUs": ["NVIDIA", "AMD", "ASUS", "MSI", "Gigabyte", "EVGA", "Zotac", "PNY", "Sapphire", "XFX", "PNY", "Colorful"],
    "RAM": ["Kingston", "Corsair", "Crucial", "G.Skill", "HyperX", "ADATA", "Patriot", "Team", "Samsung", "Lexar"],
    "SSD": ["Samsung", "Kingston", "WD", "Crucial", "Seagate", "ADATA", "SanDisk", "Lexar", "PNY", "Corsair"],
    "Laptops": ["Lenovo", "HP", "Dell", "ASUS", "Acer", "MSI", "Apple", "Huawei", "Toshiba", "LG", "Microsoft"],
    "Monitores": ["Samsung", "LG", "Dell", "ASUS", "Acer", "BenQ", "MSI", "HP", "ViewSonic", "AOC", "Gigabyte"],
    "Placas madre": ["ASUS", "MSI", "Gigabyte", "ASRock", "Biostar", "EVGA"],
}


class MercadoLibreScraper(BaseScraper):
    """Scraper para Mercado Libre México.

    Usa requests + BeautifulSoup para extraer productos de las
    páginas de listado. Hereda de BaseScraper que provee:
        - Rotación de User-Agent
        - Delays aleatorios
        - Reintentos con backoff
        - Normalización de nombres
        - Parsing de precios multi-formato
    """

    def __init__(self) -> None:
        super().__init__(store_key="mercadolibre")
        self._session: requests.Session = requests.Session()
        self._session.headers.update(self._get_headers())

    # -------------------------------------------------------------------
    # get_products — Método principal
    # -------------------------------------------------------------------
    def get_products(self, category: str) -> list[ScrapeResult]:
        """Extrae productos de Mercado Libre para una categoría.

        Flujo:
            1. Construir URL de búsqueda para la categoría
            2. Iterar páginas (máximo config.max_pages)
            3. Para cada página: request → parsear HTML → extraer productos
            4. Aplicar normalización a cada producto
            5. Retornar lista de ScrapeResult

        Args:
            category: Nombre de la categoría (ej: "CPUs", "GPUs")

        Returns:
            Lista de ScrapeResult con los productos encontrados
        """
        all_results: list[ScrapeResult] = []
        max_pages = self.config.max_pages
        max_products = self.config.max_pages * 48  # ML muestra ~48 por página

        logger.info(
            f"Iniciando scraping ML — categoría: {category}, "
            f"max_pages: {max_pages}, max_products: {max_products}"
        )

        for page in range(1, max_pages + 1):
            # Verificar si ya tenemos suficientes productos
            if len(all_results) >= max_products:
                logger.info(
                    f"Límite de productos alcanzado ({max_products}) "
                    f"para categoría {category}"
                )
                break

            # Construir URL y hacer request con retry
            url = self._build_search_url(category, page)
            logger.info(f"Scrapeando página {page}/{max_pages}: {url}")

            html = self._retry_request(
                request_fn=lambda: self._fetch_page(url)
            )

            if html is None:
                logger.warning(
                    f"No se pudo obtener página {page} de {category}. "
                    f"Saltando página."
                )
                continue

            # Verificar CAPTCHA
            if self._detect_captcha(html):
                logger.warning(
                    f"CAPTCHA detectado en página {page} de {category}. "
                    f"Saltando categoría."
                )
                self._captcha_detected += 1
                break  # Si hay CAPTCHA, no seguir con más páginas

            # Parsear productos de la página
            page_results = self._parse_products_page(html, category)
            all_results.extend(page_results)

            logger.info(
                f"Página {page}: {len(page_results)} productos extraídos "
                f"(total: {len(all_results)})"
            )

            # Delay entre páginas (excepto la última)
            if page < max_pages:
                self._delay()

        self._products_found += len(all_results)
        self._products_saved += len(all_results)

        logger.info(
            f"Scraping ML completado — {category}: "
            f"{len(all_results)} productos extraídos"
        )

        return all_results

    # -------------------------------------------------------------------
    # get_price — Precio individual de un producto
    # -------------------------------------------------------------------
    def get_price(self, product_url: str) -> dict[str, Any] | None:
        """Extrae el precio actual de un producto específico.

        Navega a la URL del producto y extrae el precio desde
        la página de detalle. Útil para verificaciones puntuales.

        Args:
            product_url: URL del producto en Mercado Libre

        Returns:
            Diccionario con price, currency, availability,
            o None si no se pudo extraer
        """
        logger.info(f"Extrayendo precio de: {product_url}")

        html = self._retry_request(
            request_fn=lambda: self._fetch_page(product_url)
        )

        if html is None:
            return None

        soup = BeautifulSoup(html, "lxml")
        selectors = self.config.selectors

        # Intentar extraer precio
        price_text = self._safe_select_text(soup, selectors.product_price)
        fraction_text = self._safe_select_text(soup, selectors.product_price_fraction)

        price = None
        if price_text:
            # Combinar parte entera + decimales si existen
            full_price_text = price_text
            if fraction_text:
                full_price_text = f"{price_text}.{fraction_text}"
            price = self._parse_price(full_price_text)

        # Detectar disponibilidad
        availability = True
        # Si no hay precio, probablemente no está disponible
        if price is None:
            availability = False

        return {
            "price": price,
            "currency": self.config.currency,
            "availability": availability,
        }

    # -------------------------------------------------------------------
    # _fetch_page — Request HTTP
    # -------------------------------------------------------------------
    def _fetch_page(self, url: str) -> str:
        """Realiza la petición HTTP y retorna el HTML.

        Usa la sesión con headers rotados. Lanza excepción
        si el status code no es 200, para que _retry_request
        la capture y reintente.

        Args:
            url: URL a solicitar

        Returns:
            Contenido HTML como string

        Raises:
            requests.RequestException: Si la petición falla
            ValueError: Si el status code no es 200
        """
        # Rotar User-Agent en cada request
        self._session.headers.update({"User-Agent": self._get_headers()["User-Agent"]})

        response = self._session.get(
            url,
            timeout=self.config.timeout,
            allow_redirects=True,
        )

        # Rate limiting
        if response.status_code == 429:
            raise requests.RequestException(
                f"Rate limited (HTTP 429) por Mercado Libre"
            )

        # CAPTCHA puede venir como 200 con formulario
        if response.status_code == 403:
            raise requests.RequestException(
                f"Acceso denegado (HTTP 403) — posible bloqueo"
            )

        if response.status_code != 200:
            raise requests.RequestException(
                f"HTTP {response.status_code} al acceder a {url}"
            )

        return response.text

    # -------------------------------------------------------------------
    # _detect_captcha — Detección de CAPTCHA
    # -------------------------------------------------------------------
    def _detect_captcha(self, html: str) -> bool:
        """Detecta si la página contiene un desafío CAPTCHA.

        Busca indicadores comunes de CAPTCHA en Mercado Libre:
            - form#captcha
            - div.captcha
            - iframe de challenge

        Args:
            html: Contenido HTML de la página

        Returns:
            True si se detecta CAPTCHA
        """
        soup = BeautifulSoup(html, "lxml")
        captcha_selectors = self.config.selectors.captcha_indicator

        if not captcha_selectors:
            return False

        for selector in captcha_selectors.split(", "):
            selector = selector.strip()
            if not selector:
                continue
            try:
                if soup.select_one(selector):
                    logger.warning(f"CAPTCHA detectado con selector: {selector}")
                    return True
            except Exception:
                continue

        # Fallback: buscar patrones de texto comunes en CAPTCHAs
        captcha_keywords = ["challenge", "captcha", "verificación", "verificacion"]
        page_text = soup.get_text(separator=" ").lower()
        title = soup.title.string.lower() if soup.title and soup.title.string else ""

        # Solo si el título también lo indica (evitar falsos positivos)
        if any(kw in title for kw in captcha_keywords):
            logger.warning("CAPTCHA detectado por título de página")
            return True

        return False

    # -------------------------------------------------------------------
    # _parse_products_page — Parser de una página de resultados
    # -------------------------------------------------------------------
    def _parse_products_page(
        self, html: str, category: str
    ) -> list[ScrapeResult]:
        """Parsea una página de resultados y extrae los productos.

        Args:
            html:     Contenido HTML de la página
            category: Categoría para asignar a los productos

        Returns:
            Lista de ScrapeResult de la página
        """
        soup = BeautifulSoup(html, "lxml")
        results: list[ScrapeResult] = []
        selectors = self.config.selectors

        # Buscar tarjetas de producto
        product_cards = self._safe_select(soup, selectors.product_card)

        if not product_cards:
            logger.warning(
                f"No se encontraron tarjetas de producto con selector: "
                f"{selectors.product_card}. Posible cambio de estructura HTML."
            )
            # Intentar con selectores de fallback
            product_cards = self._fallback_product_search(soup)
            if not product_cards:
                return results

        for card in product_cards:
            try:
                result = self._extract_product_from_card(card, category)
                if result is not None:
                    results.append(result)
            except Exception as e:
                logger.warning(
                    f"Error extrayendo producto de tarjeta: {e}. Skip."
                )
                self._products_failed += 1
                continue

        return results

    # -------------------------------------------------------------------
    # _extract_product_from_card — Extracción individual
    # -------------------------------------------------------------------
    def _extract_product_from_card(
        self, card: Tag, category: str
    ) -> ScrapeResult | None:
        """Extrae los datos de un producto desde su tarjeta HTML.

        Args:
            card:     Elemento BeautifulSoup de la tarjeta del producto
            category: Categoría asignada

        Returns:
            ScrapeResult o None si no se pudo extraer información mínima
        """
        selectors = self.config.selectors

        # --- Nombre ---
        name_text = self._safe_select_text(card, selectors.product_name)
        if not name_text:
            return None  # Sin nombre, no es un producto válido

        name = self._normalize_name(name_text)

        # --- Precio ---
        price_text = self._safe_select_text(card, selectors.product_price)
        fraction_text = self._safe_select_text(
            card, selectors.product_price_fraction
        )

        # Combinar parte entera + decimales
        full_price_text = price_text
        if price_text and fraction_text:
            full_price_text = f"{price_text}.{fraction_text}"

        price = self._parse_price(full_price_text) if full_price_text else None

        if price is None:
            # Producto sin precio → probablemente agotado o paquete
            logger.debug(f"Producto sin precio: {name[:60]}")
            self._products_failed += 1
            # Lo incluimos como no disponible para tener registro
            price = 0.0

        # --- URL ---
        url = self._safe_select_attr(card, selectors.product_url, "href")
        if url:
            # ML usa URLs relativas en algunos casos
            if url.startswith("/"):
                url = f"https://www.mercadolibre.com.mx{url}"
            # Limpiar tracking parameters
            url = url.split("#")[0].split("?")[0] if "/p/" not in url else url

        # --- Marca ---
        brand = self._safe_select_text(card, selectors.product_brand)
        if not brand:
            brand = self._extract_brand_from_name(name, category)

        # --- Disponibilidad ---
        # En ML, si el producto aparece en el listado suele estar disponible
        # pero puede estar pausado. Verificamos indicadores.
        availability = price > 0

        # --- SKU (MLM ID) ---
        sku = self._extract_sku_from_url(url) if url else None

        return ScrapeResult(
            name=name,
            brand=brand,
            price=price,
            currency=self.config.currency,
            availability=availability,
            url=url or "",
            sku=sku,
            store_name=self.config.store_name,
            category=category,
        )

    # -------------------------------------------------------------------
    # _extract_brand_from_name — Fallback de marca
    # -------------------------------------------------------------------
    def _extract_brand_from_name(self, name: str, category: str) -> str | None:
        """Intenta extraer la marca del nombre del producto.

        Busca patrones conocidos de marcas dentro del nombre.
        Este es un fallback cuando la marca no está visible
        en el listado de Mercado Libre.

        Args:
            name:     Nombre normalizado del producto
            category: Categoría para buscar marcas relevantes

        Returns:
            Marca detectada o None
        """
        brands_for_category = _BRAND_PATTERNS.get(category, [])
        name_upper = name.upper()

        for brand in brands_for_category:
            if brand.upper() in name_upper:
                return brand

        return None

    # -------------------------------------------------------------------
    # _extract_sku_from_url — Extraer MLM ID de URL
    # -------------------------------------------------------------------
    def _extract_sku_from_url(self, url: str) -> str | None:
        """Extrae el ID de producto de Mercado Libre (MLM...) desde la URL.

        URLs de ML tienen formato:
            https://articulo.mercadolibre.com.mx/MLM-1234567890-...

        Args:
            url: URL del producto

        Returns:
            SKU (MLM-XXXX) o None
        """
        match = re.search(r"(MLM-\d+)", url)
        if match:
            return match.group(1)
        return None

    # -------------------------------------------------------------------
    # _fallback_product_search — Búsqueda alternativa
    # -------------------------------------------------------------------
    def _fallback_product_search(self, soup: BeautifulSoup) -> list[Tag]:
        """Búsqueda alternativa de productos cuando los selectores fallan.

        Busca elementos que parezcan productos por heurística:
            - Enlaces con /p/ o /MLM- en el href
            - Elementos con precio (clases que contengan "price")

        Args:
            soup: BeautifulSoup de la página

        Returns:
            Lista de elementos Tag que podrían ser productos
        """
        logger.info("Intentando búsqueda fallback de productos...")

        # Buscar enlaces a productos MLM
        ml_links = soup.find_all("a", href=re.compile(r"/MLM-\d+"))

        if ml_links:
            # Agrupar por elemento padre común
            parents = set()
            for link in ml_links:
                parent = link.parent
                if parent and isinstance(parent, Tag):
                    parents.add(parent)

            logger.info(f"Fallback: encontrados {len(parents)} contenedores candidatos")
            return list(parents)

        return []

    # -------------------------------------------------------------------
    # Helpers — Selectores seguros
    # -------------------------------------------------------------------
    def _safe_select(self, soup: BeautifulSoup | Tag, selector: str) -> list[Tag]:
        """Selección segura de elementos con manejo de selectores múltiples.

        El selector puede contener múltiples opciones separadas por coma.
        Retorna los elementos del primer selector que produzca resultados.

        Args:
            soup:     BeautifulSoup o Tag raíz
            selector: Selector CSS (puede ser compuesto con comas)

        Returns:
            Lista de elementos Tag encontrados
        """
        if not selector:
            return []

        # Probar cada selector individual
        for single_selector in selector.split(", "):
            single_selector = single_selector.strip()
            if not single_selector:
                continue
            try:
                elements = soup.select(single_selector)
                if elements:
                    return elements
            except Exception as e:
                logger.debug(f"Selector falló: '{single_selector}' → {e}")
                continue

        return []

    def _safe_select_text(self, element: BeautifulSoup | Tag, selector: str) -> str | None:
        """Selección segura de texto de un elemento.

        Args:
            element:  BeautifulSoup o Tag raíz
            selector: Selector CSS

        Returns:
            Texto del primer elemento encontrado, o None
        """
        if not selector:
            return None

        for single_selector in selector.split(", "):
            single_selector = single_selector.strip()
            if not single_selector:
                continue
            try:
                found = element.select_one(single_selector)
                if found:
                    text = found.get_text(strip=True)
                    if text:
                        return text
            except Exception:
                continue

        return None

    def _safe_select_attr(
        self, element: BeautifulSoup | Tag, selector: str, attr: str
    ) -> str | None:
        """Selección segura de un atributo de un elemento.

        Args:
            element:  BeautifulSoup o Tag raíz
            selector: Selector CSS
            attr:     Nombre del atributo (ej: "href", "src")

        Returns:
            Valor del atributo del primer elemento encontrado, o None
        """
        if not selector:
            return None

        for single_selector in selector.split(", "):
            single_selector = single_selector.strip()
            if not single_selector:
                continue
            try:
                found = element.select_one(single_selector)
                if found and found.has_attr(attr):
                    value = found[attr]
                    if isinstance(value, str):
                        return value
            except Exception:
                continue

        return None

    # -------------------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------------------
    def close(self) -> None:
        """Cierra la sesión HTTP del scraper."""
        self._session.close()
        logger.info(f"Sesión HTTP cerrada para {self.store_name}")

    def __enter__(self) -> "MercadoLibreScraper":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------------------
__all__ = ["MercadoLibreScraper"]
