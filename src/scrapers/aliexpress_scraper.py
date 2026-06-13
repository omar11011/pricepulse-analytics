"""
PricePulse Analytics — Scraper de AliExpress.

Scraper concreto que extrae productos tecnológicos desde aliexpress.com
usando Playwright para renderizar JavaScript. AliExpress carga todo su
contenido dinámicamente vía JS, por lo que requests+BS4 es insuficiente.

Estrategia de extracción:
    AliExpress renderiza las páginas de búsqueda completamente vía JavaScript.
    Se usa Playwright en modo headless para:
        1. Navegar a la URL de búsqueda por categoría
        2. Esperar explícitamente a que aparezcan los selectores de producto
        3. Extraer los datos del DOM renderizado
        4. Navegar a la siguiente página si aplica

    URL de búsqueda:
        https://www.aliexpress.com/w/wholesale-{query}.html?page={page}

    Donde {query} es el término de búsqueda con guiones y {page}
    es el número de página.

Manejo de errores:
    - CAPTCHA: AliExpress usa el sistema "Baxia" (滑块验证) y
      "AliVerify" (nc_1_wrapper). Si se detectan, se salta la categoría
      y se loguea con nivel WARNING.
    - Timeouts: Playwright timeout → retry con backoff exponencial
      vía _retry_request(). Si agota reintentos, skip del producto.
    - Productos sin precio: Se registran como no disponibles.
    - Cambios de estructura: Los selectores de AliExpress cambian
      frecuentemente (clasenames con hashes). Se usan selectores
      compuestos con fallbacks.

Limitaciones conocidas:
    - Los precios en AliExpress se muestran en USD pero pueden variar
      según la región detectada por IP. Se configura currency="USD"
      pero el precio real puede estar en MXN si AliExpress detecta
      México. El módulo de transformación se encarga de la conversión.
    - La marca no siempre está visible en el listado; se intenta
      extraer del nombre del producto como fallback.
    - AliExpress actualiza sus selectores CSS con mucha frecuencia
      (clasenames con hashes aleatorios). Si el scraper retorna 0
      productos, verificar scraper_config.py.
    - El rendering con Playwright es más lento que requests+BS4
      (~5-15s por página vs ~1-3s).

Uso:
    async with AliExpressScraper() as scraper:
        results = scraper.get_products("CPUs")
        for r in results:
            print(r.name, r.price, r.currency)
"""

import re
import time
from typing import Any

from loguru import logger
from playwright.sync_api import (
    Browser,
    BrowserContext,
    ElementHandle,
    Page,
    Playwright,
    sync_playwright,
)

from src.scrapers.base_scraper import BaseScraper, ScrapeResult


# ---------------------------------------------------------------------------
# Patrones regex para extracción de marca del nombre
# ---------------------------------------------------------------------------
_BRAND_PATTERNS: dict[str, list[str]] = {
    "CPUs": ["AMD", "Intel", "Ryzen", "Core i", "Celeron", "Xeon"],
    "GPUs": [
        "NVIDIA", "AMD", "ASUS", "MSI", "Gigabyte", "EVGA",
        "Zotac", "PNY", "Sapphire", "XFX", "Colorful",
    ],
    "RAM": [
        "Kingston", "Corsair", "Crucial", "G.Skill", "HyperX",
        "ADATA", "Patriot", "Team", "Samsung", "Lexar",
    ],
    "SSD": [
        "Samsung", "Kingston", "WD", "Crucial", "Seagate",
        "ADATA", "SanDisk", "Lexar", "PNY", "Corsair",
    ],
    "Laptops": [
        "Lenovo", "HP", "Dell", "ASUS", "Acer", "MSI",
        "Apple", "Huawei", "Toshiba", "LG", "Microsoft",
    ],
    "Monitores": [
        "Samsung", "LG", "Dell", "ASUS", "Acer", "BenQ",
        "MSI", "HP", "ViewSonic", "AOC", "Gigabyte",
    ],
    "Placas madre": ["ASUS", "MSI", "Gigabyte", "ASRock", "Biostar", "EVGA"],
}


class AliExpressScraper(BaseScraper):
    """Scraper para AliExpress usando Playwright.

    Usa Playwright en modo headless para renderizar JavaScript y
    extraer productos de las páginas de búsqueda. Hereda de BaseScraper
    que provee:
        - Rotación de User-Agent
        - Delays aleatorios
        - Reintentos con backoff
        - Normalización de nombres
        - Parsing de precios multi-formato

    Atributos de instancia:
        _playwright:  Instancia de Playwright (sync API)
        _browser:     Instancia del navegador Chromium
        _context:     Contexto del navegador con configuración regional
        _page:        Página activa para navegación
    """

    def __init__(self) -> None:
        super().__init__(store_key="aliexpress")

        # Playwright se inicializa de forma lazy en _ensure_browser()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

        logger.info(
            f"AliExpressScraper inicializado — Playwright headless, "
            f"timeout={self.config.timeout}s, delays={self.config.delay_min}-{self.config.delay_max}s"
        )

    # -------------------------------------------------------------------
    # Gestión del navegador Playwright
    # -------------------------------------------------------------------
    def _ensure_browser(self) -> Page:
        """Inicializa Playwright si no está activo y retorna la página.

        Crea el navegador en modo headless con configuración anti-detección:
            - Viewport 1920x1080 (desktop)
            - Locale es-MX para precios en MXN/USD
            - Timezone America/Mexico_City
            - User-Agent rotado del pool
            - JavaScript habilitado

        Returns:
            Page activa de Playwright lista para navegar
        """
        if self._page is not None and not self._page.is_closed():
            return self._page

        logger.info("Inicializando Playwright para AliExpress...")

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-infobars",
                "--window-size=1920,1080",
            ],
        )

        # Contexto con configuración regional para evitar detección
        self._context = self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="es-MX",
            timezone_id="America/Mexico_City",
            user_agent=self._get_headers()["User-Agent"],
            java_script_enabled=True,
            extra_http_headers={
                "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
            },
        )

        self._page = self._context.new_page()

        # Anti-detección: remover propiedades de automatización
        self._page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['es-MX', 'es', 'en']
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
        """)

        logger.info("Playwright inicializado — Chromium headless listo")
        return self._page

    def _close_browser(self) -> None:
        """Cierra todos los recursos de Playwright en orden inverso.

        Orden de cierre: page → context → browser → playwright
        Cada paso se protege con try/except para garantizar que
        todos los recursos se liberen incluso si uno falla.
        """
        for resource, name in [
            (self._page, "page"),
            (self._context, "context"),
            (self._browser, "browser"),
        ]:
            if resource is not None:
                try:
                    resource.close()
                    logger.debug(f"Recurso Playwright cerrado: {name}")
                except Exception as e:
                    logger.warning(f"Error cerrando {name}: {e}")

        if self._playwright is not None:
            try:
                self._playwright.stop()
                logger.debug("Playwright detenido")
            except Exception as e:
                logger.warning(f"Error deteniendo Playwright: {e}")

        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

        logger.info(f"Navegador Playwright cerrado para {self.store_name}")

    # -------------------------------------------------------------------
    # get_products — Método principal
    # -------------------------------------------------------------------
    def get_products(self, category: str) -> list[ScrapeResult]:
        """Extrae productos de AliExpress para una categoría.

        Flujo:
            1. Inicializar Playwright si no está activo
            2. Construir URL de búsqueda para la categoría
            3. Navegar a la URL y esperar a que carguen los productos
            4. Extraer productos del DOM renderizado
            5. Navegar a la siguiente página si hay más resultados
            6. Aplicar normalización a cada producto
            7. Retornar lista de ScrapeResult

        Args:
            category: Nombre de la categoría (ej: "CPUs", "GPUs")

        Returns:
            Lista de ScrapeResult con los productos encontrados
        """
        all_results: list[ScrapeResult] = []
        max_pages = self.config.max_pages
        max_products = self.config.max_pages * 60  # AE muestra ~60 por página

        logger.info(
            f"Iniciando scraping AliExpress — categoría: {category}, "
            f"max_pages: {max_pages}, max_products: {max_products}"
        )

        page = self._ensure_browser()

        for page_num in range(1, max_pages + 1):
            # Verificar si ya tenemos suficientes productos
            if len(all_results) >= max_products:
                logger.info(
                    f"Límite de productos alcanzado ({max_products}) "
                    f"para categoría {category}"
                )
                break

            # Construir URL de búsqueda
            url = self._build_search_url(category, page_num)
            logger.info(f"Scrapeando página {page_num}/{max_pages}: {url}")

            # Navegar con retry
            success = self._retry_request(
                request_fn=lambda: self._navigate_to_page(page, url)
            )

            if not success:
                logger.warning(
                    f"No se pudo cargar página {page_num} de {category}. Saltando."
                )
                continue

            # Verificar CAPTCHA
            if self._detect_captcha(page):
                logger.warning(
                    f"CAPTCHA detectado en página {page_num} de {category}. "
                    f"Saltando categoría."
                )
                self._captcha_detected += 1
                break

            # Esperar a que carguen los productos
            products_loaded = self._wait_for_products(page)
            if not products_loaded:
                logger.warning(
                    f"Productos no cargados en página {page_num} de {category}. "
                    f"Posible cambio de estructura o sin resultados."
                )
                # Verificar si hay mensaje de "sin resultados"
                if self._check_no_results(page):
                    logger.info(f"Sin resultados para {category} en página {page_num}")
                    break
                continue

            # Extraer productos del DOM renderizado
            page_results = self._extract_products_from_page(page, category)
            all_results.extend(page_results)

            logger.info(
                f"Página {page_num}: {len(page_results)} productos extraídos "
                f"(total: {len(all_results)})"
            )

            # Delay entre páginas (excepto la última)
            if page_num < max_pages:
                self._delay()

        self._products_found += len(all_results)
        self._products_saved += len(all_results)

        logger.info(
            f"Scraping AliExpress completado — {category}: "
            f"{len(all_results)} productos extraídos"
        )

        return all_results

    # -------------------------------------------------------------------
    # get_price — Precio individual de un producto
    # -------------------------------------------------------------------
    def get_price(self, product_url: str) -> dict[str, Any] | None:
        """Extrae el precio actual de un producto específico.

        Navega a la URL del producto con Playwright y extrae el
        precio desde la página de detalle renderizada. Útil para
        verificaciones puntuales fuera del flujo masivo.

        Args:
            product_url: URL del producto en AliExpress

        Returns:
            Diccionario con price, currency, availability,
            o None si no se pudo extraer
        """
        logger.info(f"Extrayendo precio de: {product_url}")

        page = self._ensure_browser()

        success = self._retry_request(
            request_fn=lambda: self._navigate_to_page(page, product_url)
        )

        if not success:
            return None

        # Esperar a que cargue el precio en la página de detalle
        try:
            selectors = self.config.selectors
            # En página de detalle, el selector de precio puede ser diferente
            detail_price_selectors = [
                selectors.product_price,
                "span.product-price-value",
                "span.uniform-banner-box-price",
                "div.product-price",
            ]

            for selector in detail_price_selectors:
                for single_sel in selector.split(", "):
                    single_sel = single_sel.strip()
                    if not single_sel:
                        continue
                    try:
                        page.wait_for_selector(
                            single_sel,
                            timeout=self.config.timeout * 1000,
                        )
                        price_element = page.query_selector(single_sel)
                        if price_element:
                            price_text = price_element.inner_text()
                            price = self._parse_price(price_text)
                            if price is not None:
                                return {
                                    "price": price,
                                    "currency": self.config.currency,
                                    "availability": True,
                                }
                    except Exception:
                        continue

        except Exception as e:
            logger.warning(f"Error extrayendo precio de detalle: {e}")

        return {
            "price": None,
            "currency": self.config.currency,
            "availability": False,
        }

    # -------------------------------------------------------------------
    # _navigate_to_page — Navegación con Playwright
    # -------------------------------------------------------------------
    def _navigate_to_page(self, page: Page, url: str) -> bool:
        """Navega a una URL y verifica que la página cargó correctamente.

        Usa page.goto() con wait_until="domcontentloaded" para esperar
        a que el DOM esté disponible. Luego verifica que no haya errores
        de red o páginas de error.

        Args:
            page: Instancia de Page de Playwright
            url:  URL a navegar

        Returns:
            True si la página cargó correctamente

        Raises:
            Exception: Si la navegación falla (capturada por _retry_request)
        """
        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=self.config.timeout * 1000,
        )

        # Verificar respuesta HTTP
        if response is None:
            raise Exception(f"Sin respuesta del servidor para {url}")

        status = response.status
        if status == 429:
            raise Exception(f"Rate limited (HTTP 429) por AliExpress")
        if status == 403:
            raise Exception(f"Acceso denegado (HTTP 403) — posible bloqueo")
        if status >= 500:
            raise Exception(f"Error del servidor (HTTP {status})")
        if status >= 400:
            raise Exception(f"Error HTTP {status} al acceder a {url}")

        # Esperar un poco para que el JS renderice contenido
        page.wait_for_timeout(2000)

        return True

    # -------------------------------------------------------------------
    # _wait_for_products — Espera explícita por productos
    # -------------------------------------------------------------------
    def _wait_for_products(self, page: Page) -> bool:
        """Espera a que los productos aparezcan en el DOM.

        AliExpress carga los productos de forma asíncrona vía JavaScript.
        Este método espera explícitamente a que aparezcan los selectores
        de producto antes de intentar la extracción. Si los selectores
        no aparecen dentro del timeout, retorna False.

        Se intenta con cada selector individual del campo product_card,
        ya que AliExpress actualiza frecuentemente sus classnames.

        Args:
            page: Instancia de Page de Playwright

        Returns:
            True si los productos están disponibles en el DOM
        """
        selectors = self.config.selectors
        product_card_selectors = selectors.product_card

        if not product_card_selectors:
            return False

        # Intentar cada selector individual
        for single_selector in product_card_selectors.split(", "):
            single_selector = single_selector.strip()
            if not single_selector:
                continue

            try:
                page.wait_for_selector(
                    single_selector,
                    timeout=self.config.timeout * 1000,
                )
                # Verificar que hay al menos 1 producto
                cards = page.query_selector_all(single_selector)
                if cards:
                    logger.debug(
                        f"Productos encontrados con selector: "
                        f"'{single_selector}' ({len(cards)} elementos)"
                    )
                    return True
            except Exception as e:
                logger.debug(
                    f"Selector de producto no encontrado: "
                    f"'{single_selector}' → {e}"
                )
                continue

        # Fallback: esperar al contenedor de resultados
        search_results_selectors = selectors.search_results
        if search_results_selectors:
            for single_selector in search_results_selectors.split(", "):
                single_selector = single_selector.strip()
                if not single_selector:
                    continue
                try:
                    page.wait_for_selector(
                        single_selector,
                        timeout=self.config.timeout * 1000,
                    )
                    logger.debug(
                        f"Contenedor de resultados encontrado: '{single_selector}'"
                    )
                    return True
                except Exception:
                    continue

        logger.warning("No se encontraron productos ni contenedor de resultados")
        return False

    # -------------------------------------------------------------------
    # _detect_captcha — Detección de CAPTCHA en Playwright
    # -------------------------------------------------------------------
    def _detect_captcha(self, page: Page) -> bool:
        """Detecta si la página contiene un desafío CAPTCHA.

        AliExpress usa el sistema "Baxia" (滑块验证) que aparece
        como un overlay con slider. También puede usar "AliVerify"
        con el widget nc_1_wrapper.

        Se busca en el DOM renderizado por cada selector del campo
        captcha_indicator. También se verifica por contenido de texto
        en la página como fallback.

        Args:
            page: Instancia de Page de Playwright

        Returns:
            True si se detecta CAPTCHA
        """
        captcha_selectors = self.config.selectors.captcha_indicator

        if not captcha_selectors:
            return False

        # Buscar por selectores CSS
        for single_selector in captcha_selectors.split(", "):
            single_selector = single_selector.strip()
            if not single_selector:
                continue
            try:
                element = page.query_selector(single_selector)
                if element:
                    # Verificar que el elemento sea visible
                    if element.is_visible():
                        logger.warning(
                            f"CAPTCHA detectado con selector: '{single_selector}'"
                        )
                        return True
            except Exception:
                continue

        # Fallback: buscar en el contenido de la página
        try:
            page_text = page.inner_text("body").lower()
            captcha_keywords = [
                "slide to verify",
                "verify you are human",
                "baxia",
                "captcha",
                "aliverify",
                "verificación de seguridad",
            ]
            title = page.title().lower() if page.title() else ""

            # Solo si tanto el contenido como el título indican CAPTCHA
            # (evitar falsos positivos por menciones casuales)
            text_match = any(kw in page_text for kw in captcha_keywords)
            title_match = any(kw in title for kw in captcha_keywords)

            if text_match and title_match:
                logger.warning("CAPTCHA detectado por contenido de página")
                return True

        except Exception as e:
            logger.debug(f"No se pudo verificar CAPTCHA en texto: {e}")

        return False

    # -------------------------------------------------------------------
    # _check_no_results — Verificar página sin resultados
    # -------------------------------------------------------------------
    def _check_no_results(self, page: Page) -> bool:
        """Verifica si la página indica que no hay resultados.

        Args:
            page: Instancia de Page de Playwright

        Returns:
            True si se detecta mensaje de "sin resultados"
        """
        no_results_selector = self.config.selectors.no_results
        if not no_results_selector:
            return False

        for single_selector in no_results_selector.split(", "):
            single_selector = single_selector.strip()
            if not single_selector:
                continue
            try:
                element = page.query_selector(single_selector)
                if element and element.is_visible():
                    return True
            except Exception:
                continue

        return False

    # -------------------------------------------------------------------
    # _extract_products_from_page — Extracción desde DOM renderizado
    # -------------------------------------------------------------------
    def _extract_products_from_page(
        self, page: Page, category: str
    ) -> list[ScrapeResult]:
        """Extrae productos del DOM renderizado por Playwright.

        Itera sobre las tarjetas de producto encontradas y extrae
        los datos de cada una usando los selectores configurados.

        Args:
            page:     Instancia de Page de Playwright con productos cargados
            category: Categoría para asignar a los productos

        Returns:
            Lista de ScrapeResult de la página
        """
        results: list[ScrapeResult] = []
        selectors = self.config.selectors

        # Buscar tarjetas de producto
        product_cards = self._query_selector_all(page, selectors.product_card)

        if not product_cards:
            logger.warning(
                f"No se encontraron tarjetas de producto con selector: "
                f"{selectors.product_card}. Posible cambio de estructura HTML."
            )
            # Intentar búsqueda fallback
            product_cards = self._fallback_product_search(page)
            if not product_cards:
                return results

        logger.debug(f"Encontradas {len(product_cards)} tarjetas de producto")

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
        self, card: ElementHandle, category: str
    ) -> ScrapeResult | None:
        """Extrae los datos de un producto desde su tarjeta en el DOM.

        Args:
            card:     ElementHandle de Playwright de la tarjeta del producto
            category: Categoría asignada

        Returns:
            ScrapeResult o None si no se pudo extraer información mínima
        """
        selectors = self.config.selectors

        # --- Nombre ---
        name_text = self._safe_inner_text(card, selectors.product_name)
        if not name_text:
            return None  # Sin nombre, no es un producto válido

        name = self._normalize_name(name_text)

        # --- Precio ---
        price_text = self._safe_inner_text(card, selectors.product_price)
        price = self._parse_price(price_text) if price_text else None

        if price is None:
            # Producto sin precio → probablemente agotado o promoción especial
            logger.debug(f"Producto sin precio: {name[:60]}")
            self._products_failed += 1
            price = 0.0

        # --- URL ---
        url = self._safe_get_attribute(card, selectors.product_url, "href")
        if url:
            # AliExpress usa URLs relativas en algunos casos
            if url.startswith("/"):
                url = f"{self.config.base_url}{url}"
            # Limpiar parámetros de tracking
            url = self._clean_url(url)

        # --- Marca ---
        brand = self._safe_inner_text(card, selectors.product_brand)
        if not brand:
            brand = self._extract_brand_from_name(name, category)

        # --- Disponibilidad ---
        # En AliExpress, si el producto aparece en el listado suele estar disponible
        availability = price > 0

        # --- SKU (Item ID) ---
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
        en el listado de AliExpress (muy común).

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
    # _extract_sku_from_url — Extraer Item ID de URL
    # -------------------------------------------------------------------
    def _extract_sku_from_url(self, url: str) -> str | None:
        """Extrae el ID de producto de AliExpress desde la URL.

        URLs de AliExpress tienen formato:
            https://www.aliexpress.com/item/1234567890.html
            https://www.aliexpress.com/item/1234567890.html?...

        Args:
            url: URL del producto

        Returns:
            SKU (Item ID) o None
        """
        match = re.search(r"/item/(\d+)", url)
        if match:
            return f"AE-{match.group(1)}"
        return None

    # -------------------------------------------------------------------
    # _clean_url — Limpiar URL de tracking
    # -------------------------------------------------------------------
    def _clean_url(self, url: str) -> str:
        """Limpia parámetros de tracking de una URL de AliExpress.

        AliExpress añade muchos parámetros de tracking (alg_*, spm, scm, etc.)
        que no son necesarios y hacen las URLs muy largas.

        Args:
            url: URL con posibles parámetros de tracking

        Returns:
            URL limpia con solo el path esencial
        """
        # Eliminar fragment (#)
        url = url.split("#")[0]
        # Para URLs de item, mantener solo /item/ID.html
        item_match = re.match(r"(https?://[^/]+/item/\d+\.html)", url)
        if item_match:
            return item_match.group(1)
        # Para otras URLs, eliminar query params conocidos de tracking
        tracking_params = [
            "alg", "spm", "scm", "pdp_ext_f", "pdp_npi",
            "sourceType", "source", "groupId", "traceId",
        ]
        if "?" in url:
            base, query = url.split("?", 1)
            params = query.split("&")
            clean_params = [
                p for p in params
                if not any(p.startswith(f"{tp}=") for tp in tracking_params)
            ]
            if clean_params:
                return f"{base}?{'&'.join(clean_params)}"
            return base
        return url

    # -------------------------------------------------------------------
    # _fallback_product_search — Búsqueda alternativa
    # -------------------------------------------------------------------
    def _fallback_product_search(self, page: Page) -> list[ElementHandle]:
        """Búsqueda alternativa de productos cuando los selectores fallan.

        Busca elementos que parezcan productos por heurística:
            - Enlaces que contengan /item/ en el href
            - Elementos con atributos data-product o data-item

        Args:
            page: Instancia de Page de Playwright

        Returns:
            Lista de ElementHandle que podrían ser productos
        """
        logger.info("Intentando búsqueda fallback de productos...")

        # Buscar enlaces a productos (/item/ID.html)
        try:
            item_links = page.query_selector_all('a[href*="/item/"]')
            if item_links:
                # Obtener los contenedores padres de los enlaces
                parents: list[ElementHandle] = []
                seen_parents: set[str] = set()

                for link in item_links[:60]:  # Limitar a 60 productos
                    try:
                        parent = link.evaluate_handle(
                            "el => el.closest('div[class]') || el.parentElement"
                        )
                        if parent:
                            parent_id = id(parent)
                            if parent_id not in seen_parents:
                                parents.append(parent.as_element())  # type: ignore
                                seen_parents.add(parent_id)
                    except Exception:
                        continue

                if parents:
                    logger.info(
                        f"Fallback: encontrados {len(parents)} contenedores candidatos"
                    )
                    return parents
        except Exception as e:
            logger.debug(f"Fallback por enlaces falló: {e}")

        return []

    # -------------------------------------------------------------------
    # Helpers — Selectores seguros con Playwright
    # -------------------------------------------------------------------
    def _query_selector_all(
        self, page_or_element: Page | ElementHandle, selector: str
    ) -> list[ElementHandle]:
        """Selección segura de elementos con manejo de selectores múltiples.

        El selector puede contener múltiples opciones separadas por coma.
        Retorna los elementos del primer selector que produzca resultados.

        Args:
            page_or_element: Page o ElementHandle raíz
            selector:        Selector CSS (puede ser compuesto con comas)

        Returns:
            Lista de ElementHandle encontrados
        """
        if not selector:
            return []

        for single_selector in selector.split(", "):
            single_selector = single_selector.strip()
            if not single_selector:
                continue
            try:
                elements = page_or_element.query_selector_all(single_selector)
                if elements:
                    return elements
            except Exception as e:
                logger.debug(f"Selector falló: '{single_selector}' → {e}")
                continue

        return []

    def _safe_inner_text(
        self, element: ElementHandle, selector: str
    ) -> str | None:
        """Selección segura del texto interior de un elemento.

        Busca dentro del elemento dado usando el selector proporcionado.
        Si el selector es compuesto (comas), intenta cada opción individual.

        Args:
            element:  ElementHandle raíz para la búsqueda
            selector: Selector CSS

        Returns:
            Texto interior del primer elemento encontrado, o None
        """
        if not selector:
            return None

        for single_selector in selector.split(", "):
            single_selector = single_selector.strip()
            if not single_selector:
                continue
            try:
                found = element.query_selector(single_selector)
                if found:
                    text = found.inner_text()
                    if text and text.strip():
                        return text.strip()
            except Exception:
                continue

        return None

    def _safe_get_attribute(
        self, element: ElementHandle, selector: str, attr: str
    ) -> str | None:
        """Selección segura de un atributo de un elemento.

        Args:
            element:  ElementHandle raíz para la búsqueda
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
                found = element.query_selector(single_selector)
                if found:
                    value = found.get_attribute(attr)
                    if value:
                        return value
            except Exception:
                continue

        return None

    # -------------------------------------------------------------------
    # Cleanup y Context Manager
    # -------------------------------------------------------------------
    def close(self) -> None:
        """Cierra el navegador Playwright y libera recursos."""
        self._close_browser()

    def __enter__(self) -> "AliExpressScraper":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------------------
__all__ = ["AliExpressScraper"]
