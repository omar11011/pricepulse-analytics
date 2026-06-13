"""Pipeline ETL — extract, transform, load con upsert y dedup."""

import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from loguru import logger
from sqlalchemy import and_
from sqlalchemy.orm import Session

from src.config import Categories, Stores, settings
from src.database.connection import get_session, init_db
from src.database.models import Category, PipelineLog, PriceHistory, Product, Store
from src.scrapers.aliexpress_scraper import AliExpressScraper
from src.scrapers.base_scraper import BaseScraper, ScrapeResult
from src.scrapers.mercadolibre_scraper import MercadoLibreScraper
from src.scrapers.temu_scraper import TemuScraper
from src.transformers.calculator import PriceCalculator
from src.transformers.cleaner import DataCleaner


# ---
# Status del pipeline
# ---
class PipelineStatus:
    """Status del pipeline: success, partial_success, failure."""

    SUCCESS: str = "success"
    PARTIAL_SUCCESS: str = "partial_success"
    FAILURE: str = "failure"


# ---
# Resultado de un scraper individual
# ---
class ScraperResult:
    """Resultado de un scraper individual."""

    def __init__(
        self,
        store_name: str,
        results: list[ScrapeResult] | None = None,
        categories_run: int = 0,
        categories_ok: int = 0,
        categories_fail: int = 0,
        error: str | None = None,
    ) -> None:
        self.store_name = store_name
        self.results = results or []
        self.categories_run = categories_run
        self.categories_ok = categories_ok
        self.categories_fail = categories_fail
        self.error = error

    @property
    def success(self) -> bool:
        """¿Extrajo al menos 1 producto?"""
        return len(self.results) > 0

    @property
    def total_products(self) -> int:
        """Total de productos."""
        return len(self.results)


class PricePulsePipeline:
    """Orquestador ETL — scrape → transform → load."""

    def __init__(
        self,
        categories: list[str] | None = None,
        usd_to_mxn: float | None = None,
    ) -> None:
        """Inicializa el pipeline. Si no pasas categories, usa todas."""
        self._categories: list[str] = categories or Categories.ALL
        self._cleaner: DataCleaner = DataCleaner(usd_to_mxn=usd_to_mxn)
        self._calculator: PriceCalculator = PriceCalculator()
        self._last_summary: dict[str, Any] = {}

        logger.info(
            f"PricePulsePipeline inicializado — "
            f"{len(self._categories)} categorías, "
            f"USD/MXN={self._cleaner.usd_to_mxn}"
        )

    # ---
    # Propiedades
    # ---
    @property
    def last_summary(self) -> dict[str, Any]:
        """Resumen de la última ejecución."""
        return self._last_summary.copy()

    @property
    def categories(self) -> list[str]:
        """Categorías del pipeline."""
        return self._categories.copy()

    # ---
    # run() — Método principal
    # ---
    def run(self) -> dict[str, Any]:
        """Ejecuta el pipeline completo: init BD → extract → transform → load → log."""
        start_time = time.time()
        logger.info("=" * 60)
        logger.info("PricePulse Pipeline ETL — Iniciando ejecución")
        logger.info("=" * 60)

        # 1. Inicializar BD (idempotente)
        try:
            init_db()
        except Exception as e:
            logger.error(f"No se pudo inicializar la BD: {e}")
            return self._build_summary(
                status=PipelineStatus.FAILURE,
                products_found=0,
                products_clean=0,
                products_saved=0,
                products_failed=0,
                execution_time_ms=int((time.time() - start_time) * 1000),
                scrapers_results={},
                message=f"Error inicializando BD: {e}",
            )

        # 2. EXTRACT — Ejecutar scrapers
        scraper_results = self._scrape_all()

        # Consolidar todos los ScrapeResult
        all_results: list[ScrapeResult] = []
        for sr in scraper_results.values():
            all_results.extend(sr.results)

        products_found = len(all_results)

        # 3. TRANSFORM — Limpiar y normalizar
        clean_df, products_clean = self._transform(all_results)

        # 4. LOAD — Insertar en BD
        products_saved, products_failed = self._load(clean_df)

        # 5. Calcular tiempo total
        execution_time_ms = int((time.time() - start_time) * 1000)

        # 6. Determinar status
        scrapers_ok = sum(1 for sr in scraper_results.values() if sr.success)
        scrapers_total = len(scraper_results)

        if products_saved > 0 and scrapers_ok == scrapers_total:
            status = PipelineStatus.SUCCESS
        elif products_saved > 0:
            status = PipelineStatus.PARTIAL_SUCCESS
        else:
            status = PipelineStatus.FAILURE

        # 7. Construir mensaje
        message = self._build_status_message(
            status, products_found, products_clean,
            products_saved, products_failed, scraper_results,
        )

        # 8. Registrar en pipeline_logs
        self._log_execution(
            status=status,
            products_found=products_found,
            products_saved=products_saved,
            products_failed=products_failed,
            execution_time_ms=execution_time_ms,
            message=message,
        )

        # 9. Construir resumen
        summary = self._build_summary(
            status=status,
            products_found=products_found,
            products_clean=products_clean,
            products_saved=products_saved,
            products_failed=products_failed,
            execution_time_ms=execution_time_ms,
            scrapers_results=scraper_results,
            message=message,
        )

        logger.info("=" * 60)
        logger.info(
            f"Pipeline ETL completado — {status.upper()} | "
            f"Encontrados: {products_found} | "
            f"Limpios: {products_clean} | "
            f"Guardados: {products_saved} | "
            f"Fallidos: {products_failed} | "
            f"Tiempo: {execution_time_ms / 1000:.1f}s"
        )
        logger.info("=" * 60)

        return summary

    # ---
    # EXTRACT — Ejecutar scrapers
    # ---
    def _scrape_all(self) -> dict[str, ScraperResult]:
        """Ejecuta los 3 scrapers en orden. Si uno falla, continúa con los demás."""
        scraper_results: dict[str, ScraperResult] = {}

        # Definir scrapers en orden de ejecución
        scraper_configs: list[tuple[str, type[BaseScraper]]] = [
            ("Mercado Libre", MercadoLibreScraper),
            ("AliExpress", AliExpressScraper),
            ("Temu", TemuScraper),
        ]

        for store_name, scraper_class in scraper_configs:
            logger.info(f"--- Iniciando scraper: {store_name} ---")

            sr = self._run_scraper(store_name, scraper_class)
            scraper_results[store_name] = sr

            if sr.error:
                logger.error(
                    f"Scraper {store_name} falló completamente: {sr.error}"
                )
            else:
                logger.info(
                    f"Scraper {store_name} completado: "
                    f"{sr.total_products} productos, "
                    f"{sr.categories_ok}/{sr.categories_run} categorías OK"
                )

        return scraper_results

    def _run_scraper(
        self, store_name: str, scraper_class: type[BaseScraper]
    ) -> ScraperResult:
        """Ejecuta un scraper para todas las categorías."""
        sr = ScraperResult(store_name=store_name)

        try:
            with scraper_class() as scraper:
                categories_ok = 0
                categories_fail = 0

                for category in self._categories:
                    try:
                        logger.info(
                            f"Scraping {store_name} → {category}"
                        )
                        results = scraper.get_products(category)
                        sr.results.extend(results)

                        if results:
                            categories_ok += 1
                            logger.info(
                                f"  {category}: {len(results)} productos"
                            )
                        else:
                            categories_fail += 1
                            logger.warning(
                                f"  {category}: 0 productos extraídos"
                            )

                    except Exception as e:
                        categories_fail += 1
                        logger.warning(
                            f"  {category}: Error — {type(e).__name__}: {e}"
                        )
                        continue

                    # Delay entre categorías
                    if category != self._categories[-1]:
                        scraper._delay()

                sr.categories_run = len(self._categories)
                sr.categories_ok = categories_ok
                sr.categories_fail = categories_fail

        except Exception as e:
            sr.error = f"{type(e).__name__}: {e}"
            logger.error(f"Scraper {store_name} falló: {sr.error}")

        return sr

    # ---
    # TRANSFORM — Limpiar y normalizar
    # ---
    def _transform(
        self, results: list[ScrapeResult]
    ) -> tuple[pd.DataFrame, int]:
        """Limpia datos y calcula variaciones de precio."""
        logger.info(f"Transformando {len(results)} productos crudos...")

        # 1. Limpieza completa
        clean_df = self._cleaner.clean_all(results)
        products_clean = len(clean_df)

        if clean_df.empty:
            logger.warning("DataFrame vacío después de limpieza")
            return clean_df, 0

        # 2. Calcular variaciones de precio
        #    Usamos el modo DataFrame (sin BD) porque los datos aún
        #    no están insertados. Las variaciones vs BD se calculan
        #    durante _load() cuando ya tenemos los product_ids.
        clean_df = self._calculator.calculate_changes(clean_df)

        logger.info(
            f"Transformación completada: {products_clean} productos limpios"
        )

        return clean_df, products_clean

    # ---
    # LOAD — Insertar en BD con upsert
    # ---
    def _load(self, df: pd.DataFrame) -> tuple[int, int]:
        """Upsert products + insert price_history con dedup."""
        if df.empty:
            logger.warning("DataFrame vacío — nada que insertar")
            return 0, 0

        products_saved = 0
        products_failed = 0

        logger.info(f"Insertando {len(df)} productos en BD...")

        try:
            with get_session() as session:
                for idx, row in df.iterrows():
                    try:
                        # 1. Upsert product (insertar o actualizar)
                        product = self._upsert_product(session, row)

                        if product is None:
                            products_failed += 1
                            continue

                        # 2. Insert price history con deduplicación
                        price_change, price_change_pct = (
                            self._compute_price_changes(session, product, row)
                        )

                        inserted = self._insert_price_history(
                            session, product, row, price_change, price_change_pct
                        )

                        if inserted:
                            products_saved += 1
                        else:
                            # Registro duplicado para hoy — no es un error
                            logger.debug(
                                f"Registro de precio duplicado para "
                                f"'{product.name[:40]}' — omitido"
                            )
                            products_saved += 1  # Contar como éxito

                    except Exception as e:
                        products_failed += 1
                        logger.warning(
                            f"Error insertando fila {idx}: "
                            f"{type(e).__name__}: {e}"
                        )
                        continue

                # Commit explícito (el context manager hace commit al salir)
                logger.info(
                    f"Carga en BD: {products_saved} guardados, "
                    f"{products_failed} fallidos"
                )

        except Exception as e:
            logger.error(f"Error de conexión a BD durante carga: {e}")
            products_failed = len(df) - products_saved

        return products_saved, products_failed

    def _upsert_product(self, session: Session, row: pd.Series) -> Product | None:
        """Upsert de producto — inserta nuevo o actualiza brand/url/sku si ya existe."""
        try:
            name = str(row.get("name", ""))
            store_id = int(row.get("store_id", 0))

            # Buscar producto existente
            existing = session.query(Product).filter(
                and_(
                    Product.name == name,
                    Product.store_id == store_id,
                )
            ).first()

            if existing:
                # Actualizar campos mutables
                existing.brand = str(row.get("brand")) if pd.notna(row.get("brand")) else None
                existing.url = str(row.get("url")) if pd.notna(row.get("url")) else None
                existing.sku = str(row.get("sku")) if pd.notna(row.get("sku")) else None
                # Actualizar categoría si cambió
                existing.category_id = int(row.get("category_id", existing.category_id))

                logger.debug(f"Producto actualizado: {name[:50]}")
                return existing
            else:
                # Insertar nuevo producto
                new_product = Product(
                    name=name,
                    brand=str(row.get("brand")) if pd.notna(row.get("brand")) else None,
                    url=str(row.get("url")) if pd.notna(row.get("url")) else None,
                    sku=str(row.get("sku")) if pd.notna(row.get("sku")) else None,
                    category_id=int(row.get("category_id")),
                    store_id=store_id,
                )
                session.add(new_product)
                # Flush para obtener el ID asignado
                session.flush()

                logger.debug(f"Producto insertado: {name[:50]} (id={new_product.id})")
                return new_product

        except Exception as e:
            logger.warning(
                f"Error en upsert de producto: {type(e).__name__}: {e}"
            )
            return None

    def _insert_price_history(
        self,
        session: Session,
        product: Product,
        row: pd.Series,
        price_change: float | None,
        price_change_pct: float | None,
    ) -> bool:
        """Inserta en price_history — un registro por producto por día, actualiza si cambió el precio."""
        try:
            price = float(row.get("price", 0))
            currency = str(row.get("currency", "MXN"))
            availability = bool(row.get("availability", True))

            # Parsear scraped_at
            scraped_at_str = str(row.get("scraped_at", ""))
            try:
                scraped_at = datetime.strptime(scraped_at_str, "%Y-%m-%d %H:%M:%S")
                scraped_at = scraped_at.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                scraped_at = datetime.now(timezone.utc)

            # Deduplicación: verificar si ya existe registro para hoy
            today_start = scraped_at.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            today_end = scraped_at.replace(
                hour=23, minute=59, second=59, microsecond=999999
            )

            existing = session.query(PriceHistory).filter(
                and_(
                    PriceHistory.product_id == product.id,
                    PriceHistory.scraped_at >= today_start,
                    PriceHistory.scraped_at <= today_end,
                )
            ).first()

            if existing:
                # Ya existe registro para hoy — actualizar precio si es diferente
                if existing.price != price:
                    # Recalcular variaciones con el nuevo precio
                    existing.price = price
                    existing.currency = currency
                    existing.availability = availability
                    existing.price_change = price_change
                    existing.price_change_pct = price_change_pct
                    logger.debug(
                        f"Precio actualizado para hoy: {product.name[:40]} "
                        f"→ ${price:,.2f}"
                    )
                return False  # No es un insert nuevo

            # Insertar nuevo registro
            price_record = PriceHistory(
                product_id=product.id,
                price=price,
                currency=currency,
                availability=availability,
                price_change=price_change,
                price_change_pct=price_change_pct,
                scraped_at=scraped_at,
            )
            session.add(price_record)
            session.flush()

            return True

        except Exception as e:
            logger.warning(
                f"Error insertando price_history para "
                f"'{product.name[:40]}': {type(e).__name__}: {e}"
            )
            return False

    def _compute_price_changes(
        self, session: Session, product: Product, row: pd.Series
    ) -> tuple[float | None, float | None]:
        """Calcula variaciones vs último registro en BD."""
        try:
            # Obtener el último registro de precio existente
            last_record = session.query(PriceHistory).filter(
                PriceHistory.product_id == product.id
            ).order_by(PriceHistory.scraped_at.desc()).first()

            if last_record is None:
                # Primer registro del producto — sin referencia anterior
                return None, None

            current_price = float(row.get("price", 0))
            previous_price = last_record.price

            return PriceCalculator.compute_change(current_price, previous_price)

        except Exception as e:
            logger.debug(
                f"Error calculando variaciones para "
                f"'{product.name[:40]}': {e}"
            )
            return None, None

    # ---
    # LOG — Registro en pipeline_logs
    # ---
    def _log_execution(
        self,
        status: str,
        products_found: int,
        products_saved: int,
        products_failed: int,
        execution_time_ms: int,
        message: str,
    ) -> None:
        """Registra ejecución en pipeline_logs."""
        try:
            with get_session() as session:
                log_entry = PipelineLog(
                    process_name="pricepulse_etl",
                    status=status,
                    message=message[:500] if message else None,  # Limitar longitud
                    execution_time_ms=execution_time_ms,
                    products_found=products_found,
                    products_saved=products_saved,
                    products_failed=products_failed,
                )
                session.add(log_entry)

            logger.info(f"Log de ejecución registrado: {status}")

        except Exception as e:
            logger.error(
                f"No se pudo registrar log en pipeline_logs: {e}. "
                f"Pipeline result: status={status}, found={products_found}, "
                f"saved={products_saved}, failed={products_failed}"
            )

    # ---
    # Helpers — Construcción de resumen y mensajes
    # ---
    def _build_summary(
        self,
        status: str,
        products_found: int,
        products_clean: int,
        products_saved: int,
        products_failed: int,
        execution_time_ms: int,
        scrapers_results: dict[str, ScraperResult],
        message: str,
    ) -> dict[str, Any]:
        """Construye el dict de resumen de la ejecución."""
        scraper_summary = {}
        for store_name, sr in scrapers_results.items():
            scraper_summary[store_name] = {
                "products": sr.total_products,
                "categories_ok": sr.categories_ok,
                "categories_fail": sr.categories_fail,
                "error": sr.error,
            }

        summary = {
            "status": status,
            "products_found": products_found,
            "products_clean": products_clean,
            "products_saved": products_saved,
            "products_failed": products_failed,
            "execution_time_ms": execution_time_ms,
            "execution_time_s": round(execution_time_ms / 1000, 1),
            "scrapers": scraper_summary,
            "cleaner_stats": self._cleaner.stats,
            "calculator_stats": self._calculator.stats,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._last_summary = summary
        return summary

    def get_summary(self) -> dict[str, Any]:
        """Resumen de la última ejecución (vacío si no se ha ejecutado)."""
        return self._last_summary.copy()

    @staticmethod
    def _build_status_message(
        status: str,
        products_found: int,
        products_clean: int,
        products_saved: int,
        products_failed: int,
        scrapers_results: dict[str, ScraperResult],
    ) -> str:
        """Construye mensaje descriptivo del resultado."""
        parts: list[str] = []

        if status == PipelineStatus.SUCCESS:
            parts.append("Pipeline ejecutado exitosamente")
        elif status == PipelineStatus.PARTIAL_SUCCESS:
            parts.append("Pipeline ejecutado con errores parciales")
        else:
            parts.append("Pipeline falló completamente")

        parts.append(f"{products_found} productos crudos → {products_clean} limpios → {products_saved} guardados")

        if products_failed > 0:
            parts.append(f"{products_failed} productos fallidos")

        # Detalle por scraper
        for store_name, sr in scrapers_results.items():
            if sr.error:
                parts.append(f"{store_name}: FALLÓ ({sr.error})")
            else:
                parts.append(
                    f"{store_name}: {sr.total_products} productos "
                    f"({sr.categories_ok} cat OK, {sr.categories_fail} cat fail)"
                )

        return " | ".join(parts)


# ---
# Exportación
# ---
__all__ = [
    "PricePulsePipeline",
    "PipelineStatus",
    "ScraperResult",
]
