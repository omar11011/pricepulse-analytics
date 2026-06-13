"""
PricePulse Analytics — Scraper de Temu.

Scraper concreto que extrae productos tecnológicos desde temu.com
usando Playwright con configuración de sigilo para evadir la
protección anti-scraping de Cloudflare.

Estrategia de extracción:
    Temu tiene la protección anti-scraping más agresiva de las tres
    tiendas monitoreadas. Usa Cloudflare avanzado con desafíos JS,
    fingerprinting del navegador y rate limiting estricto.

    Se usa Playwright con configuración de sigilo para:
        1. Navegar a la URL de búsqueda por categoría
        2. Esperar a que se resuelva el desafío Cloudflare (si existe)
        3. Esperar explícitamente a que aparezcan los productos
        4. Extraer los datos del DOM renderizado
        5. Si una categoría es bloqueada, registrar en log y continuar

    URL de búsqueda:
        https://www.temu.com/search_result.html?search_key={query}&page={page}

    Donde {query} es el término de búsqueda y {page} es el número de página.

Configuración de sigilo:
    - Viewport 1920x1080 (desktop)
    - Locale en-US (Temu redirige si detecta es-MX)
    - Timezone America/Mexico_City
    - User-Agent rotado del pool
    - Eliminación de navigator.webdriver
    - Plugins mock para evitar detección de headless
    - Arguments de Chromium: disable-blink-features=AutomationControlled
    - Delays amplios (5-12s) para comportamiento humano

Manejo de errores:
    - Cloudflare Challenge: Se detecta por presencia de elementos
      cf-challenge, challenge-platform, o título "Just a moment".
      Si se detecta, se salta la categoría actual y se continúa con
      la siguiente. No se intenta resolver automáticamente.
    - CAPTCHA: Temu usa captcha-verify y captcha_verify_container.
      Si se detectan, se salta la categoría y se loguea.
    - Timeouts: 15s corto para no bloquear el pipeline. Si una
      categoría tarda más, se marca como fallida y se continúa.
    - Rate limiting: HTTP 429 → skip categoría completa.
    - Productos sin precio: Se registran como no disponibles.

Resiliencia:
    Este scraper está diseñado para ser resiliente ante bloqueos.
    Es EXPECTADO que tenga una tasa de éxito menor que los otros
    dos scrapers (ML y AliExpress). El pipeline ETL está diseñado
    para funcionar correctamente incluso si Temu retorna 0 productos
    en algunas o todas las categorías.

    Estrategia de fallback por categoría:
        - Si una categoría falla (Cloudflare, timeout, sin resultados),
          se registra el error y se continúa con la siguiente.
        - Los productos que SÍ se lograron extraer de categorías
          exitosas se retornan normalmente.
        - El pipeline no se detiene por fallos parciales de Temu.

Limitaciones conocidas:
    - Temu puede servir páginas de Cloudflare Challenge sin código
      de error HTTP (status 200 con JS challenge embebido).
    - Los precios en Temu se muestran en USD pero pueden variar
      según la región detectada por IP. El módulo de transformación
      se encarga de la conversión.
    - La marca casi nunca está visible en el listado de Temu;
      se extrae del nombre del producto como fallback.
    - Temu actualiza sus selectores CSS (clases con hashes) con
      frecuencia. Si el scraper retorna 0 productos, verificar
      scraper_config.py.
    - Solo se scrapea 1 página por categoría (max_pages=1) para
      minimizar la superficie de detección.

Uso:
    with TemuScraper() as scraper:
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

# ---------------------------------------------------------------------------
# Indicadores de Cloudflare Challenge
# ---------------------------------------------------------------------------
_CLOUDFLARE_INDICATORS: list[str] = [
    "#challenge-running",
    "#challenge-stage",
    "#challenge-success",
    "#challenge-error",
    "div.cf-browser-verification",
    "div#cf-challenge-running",
    "div#challenge-running",
    "iframe[src*='challenges.cloudflare.com']",
    "form#challenge-form",
]

_CLOUDFLARE_TITLE_KEYWORDS: list[str] = [
    "just a moment",
    "attention required",
    "checking your browser",
    "verify you are human",
    "cloudflare",
    "enable javascript",
    "sorry, you have been blocked",
]


class TemuScraper(BaseScraper):
    """Scraper para Temu usando Playwright con configuración de sigilo.

    Temu tiene la protección anti-scraping más agresiva (Cloudflare
    avanzado). Este scraper está diseñado para ser resiliente:

        - Si una categoría completa es bloqueada por Cloudflare,
          se registra en log y se continúa con la siguiente.
        - Timeouts cortos (15s) para no bloquear el pipeline.
        - Solo 1 página por categoría para minimizar detección.
        - Delays amplios (5-12s) para comportamiento humano.

    Hereda de BaseScraper que provee:
        - Rotación de User-Agent
        - Delays aleatorios
        - Reintentos con backoff
        - Normalización de nombres
        - Parsing de precios multi-formato

    Atributos de instancia:
        _playwright:  Instancia de Playwright (sync API)
        _browser:     Instancia del navegador Chromium
        _context:     Contexto del navegador con configuración de sigilo
        _page:        Página activa para navegación
        _categories_blocked: Lista de categorías bloqueadas en la sesión actual
    """

    def __init__(self) -> None:
        super().__init__(store_key="temu")

        # Playwright se inicializa de forma lazy en _ensure_browser()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._categories_blocked: list[str] = []

        logger.info(
            f"TemuScraper inicializado — Playwright sigilo headless, "
            f"timeout={self.config.timeout}s, delays={self.config.delay_min}-"
            f"{self.config.delay_max}s, max_pages={self.config.max_pages}"
        )
        logger.warning(
            "Temu tiene protección Cloudflare agresiva. Tasa de éxito "
            "esperada menor que ML/AliExpress. El pipeline tolera 0 productos."
        )

    # -------------------------------------------------------------------
    # Gestión del navegador Playwright (con sigilo)
    # -------------------------------------------------------------------
    def _ensure_browser(self) -> Page:
        """Inicializa Playwright si no está activo y retorna la página.

        Configuración de sigilo para evadir detección de Cloudflare:
            - Viewport 1920x1080 (desktop real)
            - Locale en-US (Temu redirige si detecta es-MX)
            - Timezone America/Mexico_City
            - User-Agent rotado del pool (Chrome desktop)
            - JavaScript habilitado
            - navigator.webdriver eliminado via init_script
            - Plugins mock para evitar detección de headless
            - Chromium args: disable-blink-features=AutomationControlled
            - Color scheme ligero (evita fingerprinting de dark mode)
            - Reduced motion preferido (comportamiento humano)

        Returns:
            Page activa de Playwright lista para navegar
        """
        if self._page is not None and not self._page.is_closed():
            return self._page

        logger.info("Inicializando Playwright con configuración de sigilo para Temu...")

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
                "--disable-extensions",
                "--disable-component-update",
                "--disable-background-networking",
                "--disable-sync",
                "--metrics-recording-only",
                "--no-first-run",
                "--safebrowsing-disable-auto-update",
            ],
        )

        # Contexto con configuración de sigilo detallada
        self._context = self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US",  # Temu redirige si detecta es-MX
            timezone_id="America/Mexico_City",
            user_agent=self._get_headers()["User-Agent"],
            java_script_enabled=True,
            color_scheme="light",
            reduced_motion="reduce",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Sec-Ch-Ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            },
        )

        self._page = self._context.new_page()

        # Anti-detección avanzada: inyectar scripts antes de cada navegación
        self._page.add_init_script("""
            // Eliminar navigator.webdriver (principal indicador de Playwright)
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
                configurable: true
            });

            // Mock de idiomas realistas
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en', 'es'],
                configurable: true
            });

            // Mock de plugins (navegador real tiene plugins)
            Object.defineProperty(navigator, 'plugins', {
                get: () => {
                    const plugins = [
                        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                        { name: 'Native Client', filename: 'internal-nacl-plugin' },
                    ];
                    plugins.length = 3;
                    return plugins;
                },
                configurable: true
            });

            // Mock de mimeTypes (consistente con plugins)
            Object.defineProperty(navigator, 'mimeTypes', {
                get: () => {
                    const mimes = [
                        { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
                        { type: 'application/x-google-chrome-pdf', suffixes: 'pdf', description: 'Portable Document Format' },
                    ];
                    mimes.length = 2;
                    return mimes;
                },
                configurable: true
            });

            // Eliminar indicadores de Playwright/Chromium automation
            delete window.__playwright;
            delete window.__pw_manual;

            // Mock de permisos (navegador real no lanza error)
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );

            // Mock de chrome runtime (solo existe en Chrome real)
            if (!window.chrome) {
                window.chrome = {
                    runtime: {
                        onConnect: {},
                        onMessage: {},
                    },
                    loadTimes: function() {},
                    csi: function() {},
                    app: {},
                };
            }

            // Override de toString para evitar detección de funciones mock
            const originalToString = Function.prototype.toString;
            Function.prototype.toString = function() {
                if (this === window.navigator.permissions.query) {
                    return 'function query() { [native code] }';
                }
                return originalToString.call(this);
            };
        """)

        # Configurar timeout por defecto para toda la página
        self._page.set_default_timeout(self.config.timeout * 1000)
        self._page.set_default_navigation_timeout(self.config.timeout * 1000)

        logger.info("Playwright sigilo inicializado — Chromium headless con anti-detección avanzada")
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
    # get_products — Método principal (resiliente por categoría)
    # -------------------------------------------------------------------
    def get_products(self, category: str) -> list[ScrapeResult]:
        """Extrae productos de Temu para una categoría.

        Diseñado para ser resiliente: si la categoría es bloqueada
        por Cloudflare o cualquier error ocurre, se registra en log
        y se retorna una lista vacía (sin crashear el pipeline).

        Flujo:
            1. Inicializar Playwright si no está activo
            2. Construir URL de búsqueda para la categoría
            3. Navegar a la URL con retry
            4. Verificar si hay desafío Cloudflare → skip si sí
            5. Verificar si hay CAPTCHA → skip si sí
            6. Esperar a que carguen los productos
            7. Extraer productos del DOM renderizado
            8. Retornar lista de ScrapeResult

        Args:
            category: Nombre de la categoría (ej: "CPUs", "GPUs")

        Returns:
            Lista de ScrapeResult con los productos encontrados.
            Puede ser vacía si la categoría fue bloqueada.
        """
        all_results: list[ScrapeResult] = []
        max_pages = self.config.max_pages  # 1 página para Temu
        max_products = max_pages * 40  # Temu muestra ~40 por página

        logger.info(
            f"Iniciando scraping Temu — categoría: {category}, "
            f"max_pages: {max_pages}, max_products esperados: {max_products}"
        )

        try:
            page = self._ensure_browser()
        except Exception as e:
            logger.error(
                f"No se pudo inicializar Playwright para Temu: {e}. "
                f"Saltando categoría {category}."
            )
            self._products_failed += 1
            self._categories_blocked.append(category)
            return all_results

        for page_num in range(1, max_pages + 1):
            try:
                # Construir URL de búsqueda
                url = self._build_search_url(category, page_num)
                logger.info(f"Scrapeando página {page_num}/{max_pages}: {url}")

                # Navegar con retry (timeout corto: 15s)
                success = self._retry_request(
                    request_fn=lambda: self._navigate_to_page(page, url),
                    max_retries=2,  # Menos reintentos para Temu (no insistir)
                    retry_delay=3,  # Retry más corto
                )

                if not success:
                    logger.warning(
                        f"No se pudo cargar página {page_num} de {category}. "
                        f"Posible bloqueo. Saltando categoría."
                    )
                    self._categories_blocked.append(category)
                    break

                # Verificar desafío Cloudflare
                if self._detect_cloudflare_challenge(page):
                    logger.warning(
                        f"☁ Cloudflare Challenge detectado en {category}. "
                        f"Saltando categoría — bloqueo registrado."
                    )
                    self._captcha_detected += 1
                    self._categories_blocked.append(category)
                    break

                # Verificar CAPTCHA propio de Temu
                if self._detect_captcha(page):
                    logger.warning(
                        f"CAPTCHA de Temu detectado en {category}. "
                        f"Saltando categoría."
                    )
                    self._captcha_detected += 1
                    self._categories_blocked.append(category)
                    break

                # Verificar página de bloqueo ("Sorry, you have been blocked")
                if self._detect_block_page(page):
                    logger.warning(
                        f"Bloqueo de IP detectado en {category}. "
                        f"Saltando categoría."
                    )
                    self._categories_blocked.append(category)
                    break

                # Esperar a que carguen los productos
                products_loaded = self._wait_for_products(page)
                if not products_loaded:
                    logger.warning(
                        f"Productos no cargados en página {page_num} de {category}. "
                        f"Posible bloqueo silencioso o cambio de estructura."
                    )
                    # Verificar sin resultados explícito
                    if self._check_no_results(page):
                        logger.info(f"Sin resultados para {category} en página {page_num}")
                    else:
                        # Posible bloqueo silencioso (Cloudflare sirvió página vacía)
                        self._categories_blocked.append(category)
                    break

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

            except Exception as e:
                # Error inesperado: registrar y continuar (resiliencia)
                logger.error(
                    f"Error inesperado scrapeando {category} página {page_num}: "
                    f"{type(e).__name__}: {e}. Saltando categoría."
                )
                self._products_failed += 1
                self._categories_blocked.append(category)
                break

        self._products_found += len(all_results)
        self._products_saved += len(all_results)

        logger.info(
            f"Scraping Temu completado — {category}: "
            f"{len(all_results)} productos extraídos"
        )

        if category in self._categories_blocked:
            logger.warning(
                f"Categoría {category} fue bloqueada durante esta sesión. "
                f"Total categorías bloqueadas: {len(self._categories_blocked)}"
            )

        return all_results

    # -------------------------------------------------------------------
    # get_products_all_categories — Ejecutar todas las categorías
    # -------------------------------------------------------------------
    def get_products_all_categories(self, categories: list[str] | None = None) -> dict[str, list[ScrapeResult]]:
        """Extrae productos de todas las categorías con estrategia de fallback.

        Si una categoría falla (Cloudflare, timeout, etc.), se continúa
        con la siguiente. Los resultados se agrupan por categoría.

        Este método es el punto de entrada recomendado para el pipeline
        ETL, ya que garantiza que se intente cada categoría de forma
        independiente.

        Args:
            categories: Lista de categorías a scrapearen.
                        Si es None, usa las 7 categorías configuradas.

        Returns:
            Diccionario {categoría: [ScrapeResult]} con los productos
            extraídos exitosamente por categoría.
        """
        from src.config import Categories

        if categories is None:
            categories = Categories.ALL

        all_results: dict[str, list[ScrapeResult]] = {}
        successful = 0
        failed = 0

        logger.info(
            f"Iniciando scraping Temu para {len(categories)} categorías: "
            f"{categories}"
        )

        for category in categories:
            try:
                results = self.get_products(category)
                all_results[category] = results
                if results:
                    successful += 1
                else:
                    failed += 1
                    logger.warning(f"Categoría {category}: 0 productos extraídos")
            except Exception as e:
                logger.error(
                    f"Error crítico en categoría {category}: {e}. Continuando..."
                )
                all_results[category] = []
                failed += 1

            # Delay entre categorías para reducir detección
            if category != categories[-1]:
                self._delay()

        logger.info(
            f"Scraping Temu completado — {successful} categorías exitosas, "
            f"{failed} fallidas de {len(categories)} totales. "
            f"Categorías bloqueadas: {self._categories_blocked}"
        )

        return all_results

    # -------------------------------------------------------------------
    # get_price — Precio individual de un producto
    # -------------------------------------------------------------------
    def get_price(self, product_url: str) -> dict[str, Any] | None:
        """Extrae el precio actual de un producto específico.

        Navega a la URL del producto con Playwright y extrae el
        precio desde la página de detalle renderizada.

        Args:
            product_url: URL del producto en Temu

        Returns:
            Diccionario con price, currency, availability,
            o None si no se pudo extraer
        """
        logger.info(f"Extrayendo precio de: {product_url}")

        try:
            page = self._ensure_browser()
        except Exception as e:
            logger.error(f"No se pudo inicializar Playwright: {e}")
            return None

        try:
            success = self._retry_request(
                request_fn=lambda: self._navigate_to_page(page, product_url),
                max_retries=2,
                retry_delay=3,
            )

            if not success:
                return None

            # Verificar Cloudflare en página de detalle
            if self._detect_cloudflare_challenge(page):
                logger.warning("Cloudflare detectado en página de detalle")
                return None

            # Intentar extraer precio con múltiples selectores
            detail_price_selectors = [
                self.config.selectors.product_price,
                "span[data-price]",
                "div.product-price span",
                "span.price-current",
            ]

            for selector in detail_price_selectors:
                for single_sel in selector.split(", "):
                    single_sel = single_sel.strip()
                    if not single_sel:
                        continue
                    try:
                        element = page.query_selector(single_sel)
                        if element:
                            price_text = element.inner_text()
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

        Usa page.goto() con wait_until="domcontentloaded" y timeout
        de 15s (configurado en _ensure_browser). Luego espera un
        breve momento para que el JS renderice contenido.

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
            raise Exception(f"Rate limited (HTTP 429) por Temu")
        if status == 403:
            raise Exception(f"Acceso denegado (HTTP 403) — bloqueo Cloudflare")
        if status >= 500:
            raise Exception(f"Error del servidor (HTTP {status})")
        if status >= 400:
            raise Exception(f"Error HTTP {status} al acceder a {url}")

        # Esperar a que el JS renderice contenido dinámico
        # Tiempo breve porque Temu carga rápido (o Cloudflare aparece rápido)
        page.wait_for_timeout(3000)

        return True

    # -------------------------------------------------------------------
    # _detect_cloudflare_challenge — Detección de Cloudflare
    # -------------------------------------------------------------------
    def _detect_cloudflare_challenge(self, page: Page) -> bool:
        """Detecta si la página contiene un desafío Cloudflare.

        Cloudflare sirve una página intermedia con JS challenge antes
        de permitir acceso al contenido real. Indicadores comunes:

        - Elementos: #challenge-running, #challenge-stage,
          div.cf-browser-verification, iframe de challenges.cloudflare.com
        - Título: "Just a moment...", "Attention Required!",
          "Checking your browser"
        - Contenido: "Enable JavaScript", "Sorry, you have been blocked"

        No se intenta resolver automáticamente el challenge porque:
        1. Los challenges de Cloudflare son sofisticados y cambian
        2. Resolverlos requiere interacción humana o tools costosas
        3. El pipeline está diseñado para tolerar fallos de Temu

        Args:
            page: Instancia de Page de Playwright

        Returns:
            True si se detecta desafío Cloudflare
        """
        # Buscar por selectores CSS de Cloudflare
        for selector in _CLOUDFLARE_INDICATORS:
            try:
                element = page.query_selector(selector)
                if element:
                    if element.is_visible():
                        logger.warning(
                            f"☁ Cloudflare Challenge detectado con selector: "
                            f"'{selector}'"
                        )
                        return True
            except Exception:
                continue

        # Fallback: verificar por título de página
        try:
            title = page.title().lower() if page.title() else ""
            for keyword in _CLOUDFLARE_TITLE_KEYWORDS:
                if keyword in title:
                    logger.warning(
                        f"☁ Cloudflare detectado por título: '{page.title()}'"
                    )
                    return True
        except Exception:
            pass

        # Fallback: verificar por contenido de la página
        try:
            body_text = page.inner_text("body").lower()
            # Buscar frases indicadoras de Cloudflare (no solo palabras sueltas)
            cf_phrases = [
                "checking your browser before accessing",
                "please complete the security check",
                "this process is automatic",
                "you have been blocked",
                "ray id",  # Cloudflare incluye un Ray ID en páginas de error
                "performance & security by cloudflare",
            ]
            for phrase in cf_phrases:
                if phrase in body_text:
                    logger.warning(
                        f"☁ Cloudflare detectado por contenido: '{phrase}'"
                    )
                    return True
        except Exception:
            pass

        return False

    # -------------------------------------------------------------------
    # _detect_captcha — Detección de CAPTCHA de Temu
    # -------------------------------------------------------------------
    def _detect_captcha(self, page: Page) -> bool:
        """Detecta si la página contiene un CAPTCHA propio de Temu.

        Temu usa un sistema de verificación propio (captcha-verify)
        además de la protección de Cloudflare. Se busca en el DOM
        renderizado por cada selector del campo captcha_indicator.

        Args:
            page: Instancia de Page de Playwright

        Returns:
            True si se detecta CAPTCHA
        """
        captcha_selectors = self.config.selectors.captcha_indicator

        if not captcha_selectors:
            return False

        for single_selector in captcha_selectors.split(", "):
            single_selector = single_selector.strip()
            if not single_selector:
                continue
            try:
                element = page.query_selector(single_selector)
                if element:
                    if element.is_visible():
                        logger.warning(
                            f"CAPTCHA de Temu detectado con selector: "
                            f"'{single_selector}'"
                        )
                        return True
            except Exception:
                continue

        return False

    # -------------------------------------------------------------------
    # _detect_block_page — Detección de página de bloqueo
    # -------------------------------------------------------------------
    def _detect_block_page(self, page: Page) -> bool:
        """Detecta si la página indica un bloqueo directo de IP.

        Temu puede servir una página de "blocked" cuando detecta
        scraping. No es Cloudflare, sino un bloqueo propio de Temu.

        Args:
            page: Instancia de Page de Playwright

        Returns:
            True si se detecta página de bloqueo
        """
        try:
            body_text = page.inner_text("body").lower()
            block_phrases = [
                "your access has been restricted",
                "unusual activity detected",
                "access denied",
                "ip has been blocked",
                "temporarily restricted",
            ]
            for phrase in block_phrases:
                if phrase in body_text:
                    logger.warning(f"Bloqueo de IP detectado: '{phrase}'")
                    return True
        except Exception:
            pass

        return False

    # -------------------------------------------------------------------
    # _wait_for_products — Espera explícita por productos
    # -------------------------------------------------------------------
    def _wait_for_products(self, page: Page) -> bool:
        """Espera a que los productos aparezcan en el DOM.

        Temu carga los productos de forma asíncrona vía JavaScript.
        Este método espera explícitamente a que aparezcan los
        selectores de producto antes de intentar la extracción.

        Tiene timeout corto (15s) configurado en _ensure_browser
        para no bloquear el pipeline si Temu no responde.

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
                        timeout=min(self.config.timeout * 1000, 10000),  # Max 10s para fallback
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

        # Fallback: buscar texto de "sin resultados"
        try:
            body_text = page.inner_text("body").lower()
            no_results_phrases = [
                "no results found",
                "0 results",
                "no items found",
                "couldn't find any matching",
                "no se encontraron resultados",
            ]
            for phrase in no_results_phrases:
                if phrase in body_text:
                    return True
        except Exception:
            pass

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
            logger.debug(f"Producto sin precio: {name[:60]}")
            self._products_failed += 1
            price = 0.0

        # --- URL ---
        url = self._safe_get_attribute(card, selectors.product_url, "href")
        if url:
            if url.startswith("/"):
                url = f"{self.config.base_url}{url}"
            url = self._clean_url(url)

        # --- Marca ---
        brand = self._safe_inner_text(card, selectors.product_brand)
        if not brand:
            brand = self._extract_brand_from_name(name, category)

        # --- Disponibilidad ---
        availability = price > 0

        # --- SKU ---
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

        Temu casi nunca muestra la marca explícitamente en el
        listado, por lo que este fallback es el principal mecanismo
        de detección de marca para productos de Temu.

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
    # _extract_sku_from_url — Extraer ID de URL de Temu
    # -------------------------------------------------------------------
    def _extract_sku_from_url(self, url: str) -> str | None:
        """Extrae el ID de producto de Temu desde la URL.

        URLs de Temu tienen formato:
            https://www.temu.com/goods-detail-g-1234567890.html
            https://www.temu.com/-g-1234567890.html

        Args:
            url: URL del producto

        Returns:
            SKU (formato TEMU-XXXXXXXXXX) o None
        """
        # Formato: /-g-XXXXXXXXXX o /goods-detail-g-XXXXXXXXXX
        match = re.search(r"-g-(\d+)", url)
        if match:
            return f"TEMU-{match.group(1)}"

        # Fallback: buscar ID numérico largo en la URL
        match = re.search(r"/(\d{8,})\.html", url)
        if match:
            return f"TEMU-{match.group(1)}"

        return None

    # -------------------------------------------------------------------
    # _clean_url — Limpiar URL de tracking
    # -------------------------------------------------------------------
    def _clean_url(self, url: str) -> str:
        """Limpia parámetros de tracking de una URL de Temu.

        Temu añade muchos parámetros de tracking y referidos que
        no son necesarios y hacen las URLs muy largas.

        Args:
            url: URL con posibles parámetros de tracking

        Returns:
            URL limpia
        """
        # Eliminar fragment (#)
        url = url.split("#")[0]

        # Para URLs de goods-detail, mantener solo el path esencial
        goods_match = re.match(
            r"(https?://[^/]+/[-\w]*-g-\d+\.html)", url
        )
        if goods_match:
            return goods_match.group(1)

        # Parámetros de tracking conocidos de Temu
        tracking_params = [
            "refer_page", "search_key", "search_meta",
            "sku_id", "ads", "page_el", "page_list",
            "obj_id", "obj_source", "scene", "sub_scene",
            "mscene", "search_result", "pdp_id",
            "_bg_ref", "_x_share_id", "_x_sessn_id",
            "src", "source", "channel",
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
            - Enlaces que contengan -g- en el href (patrón de Temu)
            - Elementos con atributos data-product o data-item

        Args:
            page: Instancia de Page de Playwright

        Returns:
            Lista de ElementHandle que podrían ser productos
        """
        logger.info("Intentando búsqueda fallback de productos...")

        # Buscar enlaces a productos (patrón -g-XXXXXXXX)
        try:
            item_links = page.query_selector_all('a[href*="-g-"]')
            if item_links:
                parents: list[ElementHandle] = []
                seen_parents: set[int] = set()

                for link in item_links[:40]:  # Limitar a 40 productos
                    try:
                        parent = link.evaluate_handle(
                            "el => el.closest('div[class]') || el.parentElement"
                        )
                        if parent:
                            element = parent.as_element()
                            if element and id(element) not in seen_parents:
                                parents.append(element)
                                seen_parents.add(id(element))
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
    # Propiedades adicionales
    # -------------------------------------------------------------------
    @property
    def categories_blocked(self) -> list[str]:
        """Lista de categorías bloqueadas durante la sesión actual."""
        return self._categories_blocked.copy()

    @property
    def blocked_count(self) -> int:
        """Número de categorías bloqueadas en la sesión actual."""
        return len(self._categories_blocked)

    # -------------------------------------------------------------------
    # Cleanup y Context Manager
    # -------------------------------------------------------------------
    def close(self) -> None:
        """Cierra el navegador Playwright y libera recursos."""
        if self._categories_blocked:
            logger.info(
                f"Sesión Temu finalizada — categorías bloqueadas: "
                f"{self._categories_blocked}"
            )
        self._close_browser()

    def __enter__(self) -> "TemuScraper":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------------------
__all__ = ["TemuScraper"]
