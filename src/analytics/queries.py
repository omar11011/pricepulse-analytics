"""Servicio de consultas analíticas — retorna DataFrames para el dashboard."""

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
from loguru import logger
from sqlalchemy import and_, desc, func, text, case
from sqlalchemy.orm import Session
from sqlalchemy.sql import expression

from src.config import settings
from src.database.connection import get_session
from src.database.models import Category, PriceHistory, Product, Store


# ---
# Dialect helpers — Abstracción SQLite vs PostgreSQL
# ---
def _dialect_extract_dow(column: Any) -> Any:
    """Extrae día de la semana (1=Lun, 7=Dom) — compatible SQLite/PostgreSQL."""
    if settings.database.is_sqlite:
        # SQLite: strftime('%w') = 0(Dom),1(Lun),...,6(Sab)
        # Convertir a ISODOW: 1(Lun),...,7(Dom)
        # Fórmula: (strftime_w + 6) % 7 + 1
        #   Dom(0) → (0+6)%7+1 = 6+1 = 7 ✅
        #   Lun(1) → (1+6)%7+1 = 0+1 = 1 ✅
        #   Sab(6) → (6+6)%7+1 = 5+1 = 6 ✅
        strftime_w = func.strftime("%w", column)
        return ((strftime_w + 6) % 7 + 1).label("day_number")
    else:
        # PostgreSQL: ISODOW nativo
        return func.extract("ISODOW", column).label("day_number")


def _dialect_stddev(column: Any) -> Any:
    """Stddev cross-dialect — PostgreSQL nativo, SQLite via fórmula poblacional."""
    if settings.database.is_sqlite:
        # SQLite: stddev = sqrt(avg(x*x) - avg(x)*avg(x))
        # Usamos la fórmula de varianza poblacional (aproximación cercana)
        return func.sqrt(
            func.avg(column * column) - func.avg(column) * func.avg(column)
        )
    else:
        return func.stddev(column)


class AnalyticsService:
    """Servicio de queries analíticas — retorna DataFrames, maneja BD vacía."""

    def __init__(self, default_days: int = 30) -> None:
        """Inicializa el servicio. default_days=30 por defecto."""
        self._default_days = default_days
        logger.info(
            f"AnalyticsService inicializado — default_days={default_days}, "
            f"dialect={settings.database.dialect_name}"
        )

    # ---
    # 1. KPI Summary — Indicadores clave del sistema
    # ---
    def get_kpi_summary(self, session: Session | None = None) -> pd.DataFrame:
        """KPIs generales: productos, tiendas, precios, descuentos."""
        logger.info("Consultando KPI summary...")

        def _query(session: Session) -> pd.DataFrame:
            # Total de productos
            total_products = session.query(func.count(Product.id)).scalar() or 0

            # Tiendas activas
            total_stores = session.query(func.count(Store.id)).scalar() or 0

            # Categorías
            total_categories = session.query(func.count(Category.id)).scalar() or 0

            # Precio promedio, mínimo, máximo (último registro por producto)
            # Usar .one() para obtener tupla (no .scalar() que retorna solo el primer valor)
            price_stats = session.query(
                func.avg(PriceHistory.price).label("avg_price"),
                func.min(PriceHistory.price).label("min_price"),
                func.max(PriceHistory.price).label("max_price"),
            ).one()

            avg_price = float(price_stats[0]) if price_stats[0] else 0.0
            min_price = float(price_stats[1]) if price_stats[1] else 0.0
            max_price = float(price_stats[2]) if price_stats[2] else 0.0

            # Productos con descuento (price_change < 0 en el registro más reciente)
            # Subquery: último registro por producto
            latest_prices = (
                session.query(
                    PriceHistory.product_id,
                    func.max(PriceHistory.scraped_at).label("latest_at"),
                )
                .group_by(PriceHistory.product_id)
                .subquery()
            )

            products_with_discount = (
                session.query(func.count(PriceHistory.id))
                .join(
                    latest_prices,
                    and_(
                        PriceHistory.product_id == latest_prices.c.product_id,
                        PriceHistory.scraped_at == latest_prices.c.latest_at,
                    ),
                )
                .filter(PriceHistory.price_change < 0)
                .scalar()
            ) or 0

            products_price_up = (
                session.query(func.count(PriceHistory.id))
                .join(
                    latest_prices,
                    and_(
                        PriceHistory.product_id == latest_prices.c.product_id,
                        PriceHistory.scraped_at == latest_prices.c.latest_at,
                    ),
                )
                .filter(PriceHistory.price_change > 0)
                .scalar()
            ) or 0

            # Última actualización
            last_update = session.query(
                func.max(PriceHistory.scraped_at)
            ).scalar()

            # Total de registros
            total_price_records = session.query(
                func.count(PriceHistory.id)
            ).scalar() or 0

            kpi_data = {
                "total_products": [total_products],
                "total_stores": [total_stores],
                "total_categories": [total_categories],
                "avg_price_mxn": [round(avg_price, 2)],
                "min_price_mxn": [round(min_price, 2)],
                "max_price_mxn": [round(max_price, 2)],
                "products_with_discount": [products_with_discount],
                "products_price_up": [products_price_up],
                "last_update": [last_update],
                "total_price_records": [total_price_records],
            }

            return pd.DataFrame(kpi_data)

        return self._execute_query(_query, session)

    # ---
    # 2. Price Evolution — Serie temporal de precios
    # ---
    def get_price_evolution(
        self,
        product_id: int | None = None,
        product_name: str | None = None,
        days: int | None = None,
        session: Session | None = None,
    ) -> pd.DataFrame:
        """Serie temporal de precios de un producto (por ID o nombre parcial)."""
        if days is None:
            days = self._default_days

        logger.info(
            f"Consultando evolución de precio: "
            f"product_id={product_id}, name={product_name}, days={days}"
        )

        def _query(session: Session) -> pd.DataFrame:
            # Buscar producto
            product = None
            if product_id:
                product = session.query(Product).filter(
                    Product.id == product_id
                ).first()
            elif product_name:
                product = session.query(Product).filter(
                    Product.name.ilike(f"%{product_name}%")
                ).first()

            if product is None:
                logger.warning(
                    f"Producto no encontrado: id={product_id}, "
                    f"name={product_name}"
                )
                return pd.DataFrame()

            # Calcular fecha límite
            since = datetime.now(timezone.utc) - timedelta(days=days)

            # Consultar historial de precios
            records = (
                session.query(
                    PriceHistory.scraped_at,
                    PriceHistory.price,
                    PriceHistory.price_change,
                    PriceHistory.price_change_pct,
                    PriceHistory.availability,
                    Product.name.label("product_name"),
                    Store.name.label("store_name"),
                )
                .join(Product, PriceHistory.product_id == Product.id)
                .join(Store, Product.store_id == Store.id)
                .filter(
                    and_(
                        PriceHistory.product_id == product.id,
                        PriceHistory.scraped_at >= since,
                    )
                )
                .order_by(PriceHistory.scraped_at.asc())
                .all()
            )

            if not records:
                return pd.DataFrame()

            df = pd.DataFrame(records, columns=[
                "date", "price", "price_change", "price_change_pct",
                "availability", "product_name", "store_name",
            ])

            # Convertir fecha a solo fecha (sin hora) para gráficos
            df["date"] = pd.to_datetime(df["date"]).dt.date

            return df

        return self._execute_query(_query, session)

    # ---
    # 3. Store Ranking — Ranking de tiendas por precio
    # ---
    def get_store_ranking(
        self,
        category_id: int | None = None,
        session: Session | None = None,
    ) -> pd.DataFrame:
        """Ranking de tiendas por precio promedio (1 = más barata)."""
        logger.info(
            f"Consultando ranking de tiendas: category_id={category_id}"
        )

        def _query(session: Session) -> pd.DataFrame:
            # Subquery: último precio por producto
            latest_prices = (
                session.query(
                    PriceHistory.product_id,
                    PriceHistory.price,
                    func.row_number().over(
                        partition_by=PriceHistory.product_id,
                        order_by=desc(PriceHistory.scraped_at),
                    ).label("rn"),
                )
                .subquery()
            )

            # Query principal: agrupar por tienda
            query = (
                session.query(
                    Store.name.label("store_name"),
                    func.avg(latest_prices.c.price).label("avg_price"),
                    func.min(latest_prices.c.price).label("min_price"),
                    func.max(latest_prices.c.price).label("max_price"),
                    func.count(Product.id).label("product_count"),
                )
                .join(Product, Product.store_id == Store.id)
                .join(latest_prices, and_(
                    latest_prices.c.product_id == Product.id,
                    latest_prices.c.rn == 1,
                ))
            )

            if category_id:
                query = query.filter(Product.category_id == category_id)

            query = query.group_by(Store.name).order_by(
                func.avg(latest_prices.c.price).asc()
            )

            results = query.all()

            if not results:
                return pd.DataFrame()

            df = pd.DataFrame(results, columns=[
                "store_name", "avg_price", "min_price",
                "max_price", "product_count",
            ])

            # Redondear precios
            for col in ["avg_price", "min_price", "max_price"]:
                df[col] = df[col].round(2)

            # Agregar ranking
            df["rank"] = range(1, len(df) + 1)

            return df

        return self._execute_query(_query, session)

    # ---
    # 4. Category Volatility — Volatilidad por categoría
    # ---
    def get_category_volatility(
        self,
        days: int | None = None,
        session: Session | None = None,
    ) -> pd.DataFrame:
        """Volatilidad de precios por categoría (stddev de price_change_pct)."""
        if days is None:
            days = self._default_days

        logger.info(f"Consultando volatilidad por categoría: days={days}")

        def _query(session: Session) -> pd.DataFrame:
            since = datetime.now(timezone.utc) - timedelta(days=days)

            results = (
                session.query(
                    Category.name.label("category_name"),
                    _dialect_stddev(PriceHistory.price_change_pct).label("volatility"),
                    func.avg(PriceHistory.price_change_pct).label("avg_change_pct"),
                    func.count(PriceHistory.id).label("price_records"),
                    func.count(func.distinct(Product.id)).label("products_count"),
                )
                .join(Product, Product.category_id == Category.id)
                .join(PriceHistory, PriceHistory.product_id == Product.id)
                .filter(
                    and_(
                        PriceHistory.scraped_at >= since,
                        PriceHistory.price_change_pct.isnot(None),
                    )
                )
                .group_by(Category.name)
                .order_by(
                    _dialect_stddev(PriceHistory.price_change_pct).desc()
                )
                .all()
            )

            if not results:
                return pd.DataFrame()

            df = pd.DataFrame(results, columns=[
                "category_name", "volatility", "avg_change_pct",
                "price_records", "products_count",
            ])

            # Redondear
            df["volatility"] = df["volatility"].round(2)
            df["avg_change_pct"] = df["avg_change_pct"].round(2)

            return df

        return self._execute_query(_query, session)

    # ---
    # 5. Top Discounts — Productos con mayor descuento
    # ---
    def get_top_discounts(
        self,
        n: int = 10,
        days: int | None = None,
        category_id: int | None = None,
        session: Session | None = None,
    ) -> pd.DataFrame:
        """Top N productos con mayor descuento reciente."""
        if days is None:
            days = self._default_days

        logger.info(
            f"Consultando top {n} descuentos: days={days}, "
            f"category_id={category_id}"
        )

        def _query(session: Session) -> pd.DataFrame:
            since = datetime.now(timezone.utc) - timedelta(days=days)

            # Subquery: último registro por producto
            latest_prices = (
                session.query(
                    PriceHistory.id,
                    PriceHistory.product_id,
                    PriceHistory.price,
                    PriceHistory.price_change,
                    PriceHistory.price_change_pct,
                    PriceHistory.scraped_at,
                    func.row_number().over(
                        partition_by=PriceHistory.product_id,
                        order_by=desc(PriceHistory.scraped_at),
                    ).label("rn"),
                )
                .filter(PriceHistory.scraped_at >= since)
                .subquery()
            )

            # Query principal: solo registros con descuento (price_change_pct < 0)
            query = (
                session.query(
                    Product.name.label("product_name"),
                    Store.name.label("store_name"),
                    Category.name.label("category_name"),
                    latest_prices.c.price.label("current_price"),
                    (latest_prices.c.price - latest_prices.c.price_change).label("previous_price"),
                    func.abs(latest_prices.c.price_change).label("discount_amount"),
                    func.abs(latest_prices.c.price_change_pct).label("discount_pct"),
                    latest_prices.c.scraped_at,
                )
                .join(Product, latest_prices.c.product_id == Product.id)
                .join(Store, Product.store_id == Store.id)
                .join(Category, Product.category_id == Category.id)
                .filter(
                    and_(
                        latest_prices.c.rn == 1,
                        latest_prices.c.price_change_pct < 0,  # Solo descuentos
                    )
                )
            )

            if category_id:
                query = query.filter(Product.category_id == category_id)

            results = query.order_by(
                latest_prices.c.price_change_pct.asc()  # Mayor descuento primero
            ).limit(n).all()

            if not results:
                return pd.DataFrame()

            df = pd.DataFrame(results, columns=[
                "product_name", "store_name", "category_name",
                "current_price", "previous_price", "discount_amount",
                "discount_pct", "scraped_at",
            ])

            # Redondear
            for col in ["current_price", "previous_price", "discount_amount"]:
                df[col] = df[col].round(2)
            df["discount_pct"] = df["discount_pct"].round(2)

            return df

        return self._execute_query(_query, session)

    # ---
    # 6. Best Time to Buy — Análisis por día de semana
    # ---
    def get_best_time_to_buy(
        self,
        category_id: int | None = None,
        days: int | None = None,
        session: Session | None = None,
    ) -> pd.DataFrame:
        """Qué día de la semana tiene los precios más bajos (ISODOW, cross-dialect)."""
        if days is None:
            days = 90  # Más días para patrones por día de semana

        logger.info(
            f"Consultando mejor momento para comprar: "
            f"category_id={category_id}, days={days}"
        )

        def _query(session: Session) -> pd.DataFrame:
            since = datetime.now(timezone.utc) - timedelta(days=days)

            # Nombres de día en español (ISODOW: 1=Lunes, 7=Domingo)
            day_names = {
                1: "Lunes", 2: "Martes", 3: "Miércoles",
                4: "Jueves", 5: "Viernes", 6: "Sábado", 7: "Domingo",
            }

            # Usar helper cross-dialect para extraer día de la semana
            dow_expr = _dialect_extract_dow(PriceHistory.scraped_at)

            # Construir query base
            query = (
                session.query(
                    dow_expr,
                    func.avg(PriceHistory.price).label("avg_price"),
                    func.min(PriceHistory.price).label("min_price"),
                    func.max(PriceHistory.price).label("max_price"),
                    func.count(PriceHistory.id).label("price_records"),
                )
                .join(Product, PriceHistory.product_id == Product.id)
                .filter(PriceHistory.scraped_at >= since)
            )

            if category_id:
                query = query.filter(Product.category_id == category_id)

            results = query.group_by(
                text("day_number")
            ).order_by(
                text("day_number")
            ).all()

            if not results:
                return pd.DataFrame()

            df = pd.DataFrame(results, columns=[
                "day_number", "avg_price", "min_price",
                "max_price", "price_records",
            ])

            # Agregar nombre del día
            df["day_number"] = df["day_number"].astype(int)
            df["day_of_week"] = df["day_number"].map(day_names)

            # Redondear precios
            for col in ["avg_price", "min_price", "max_price"]:
                df[col] = df[col].round(2)

            # Marcar el mejor día (precio promedio más bajo)
            best_day = df.loc[df["avg_price"].idxmin(), "day_number"]
            df["is_best"] = df["day_number"] == best_day

            # Reordenar columnas
            df = df[[
                "day_of_week", "day_number", "avg_price", "min_price",
                "max_price", "price_records", "is_best",
            ]]

            return df

        return self._execute_query(_query, session)

    # ---
    # 7. Price Comparison — Comparar precios entre tiendas
    # ---
    def get_price_comparison(
        self,
        product_name: str,
        session: Session | None = None,
    ) -> pd.DataFrame:
        """Compara precios de un producto entre tiendas."""
        logger.info(f"Consultando comparación de precios: {product_name}")

        def _query(session: Session) -> pd.DataFrame:
            # Buscar productos que coincidan con el nombre en todas las tiendas
            products = (
                session.query(Product)
                .filter(Product.name.ilike(f"%{product_name}%"))
                .all()
            )

            if not products:
                return pd.DataFrame()

            rows = []
            for product in products:
                # Último precio
                last_price = (
                    session.query(PriceHistory)
                    .filter(PriceHistory.product_id == product.id)
                    .order_by(desc(PriceHistory.scraped_at))
                    .first()
                )

                if last_price is None:
                    continue

                store = session.query(Store).filter(
                    Store.id == product.store_id
                ).first()

                rows.append({
                    "store_name": store.name if store else "Unknown",
                    "product_name": product.name,
                    "current_price": round(last_price.price, 2),
                    "availability": last_price.availability,
                    "last_updated": last_price.scraped_at,
                })

            if not rows:
                return pd.DataFrame()

            df = pd.DataFrame(rows)

            # Ordenar por precio
            df = df.sort_values("current_price", ascending=True).reset_index(drop=True)

            # Calcular diferencia vs más barato
            cheapest_price = df["current_price"].iloc[0]
            df["price_diff_vs_cheapest"] = (
                df["current_price"] - cheapest_price
            ).round(2)
            df["is_cheapest"] = df["current_price"] == cheapest_price

            return df

        return self._execute_query(_query, session)

    # ---
    # 8. Category Summary — Resumen por categoría
    # ---
    def get_category_summary(
        self,
        session: Session | None = None,
    ) -> pd.DataFrame:
        """Resumen de precios por categoría."""
        logger.info("Consultando resumen por categoría...")

        def _query(session: Session) -> pd.DataFrame:
            # Subquery: último precio por producto
            latest_prices = (
                session.query(
                    PriceHistory.product_id,
                    PriceHistory.price,
                    PriceHistory.price_change_pct,
                    func.row_number().over(
                        partition_by=PriceHistory.product_id,
                        order_by=desc(PriceHistory.scraped_at),
                    ).label("rn"),
                )
                .subquery()
            )

            results = (
                session.query(
                    Category.name.label("category_name"),
                    func.count(Product.id).label("product_count"),
                    func.avg(latest_prices.c.price).label("avg_price"),
                    func.min(latest_prices.c.price).label("min_price"),
                    func.max(latest_prices.c.price).label("max_price"),
                    func.avg(latest_prices.c.price_change_pct).label("avg_discount_pct"),
                )
                .join(Product, Product.category_id == Category.id)
                .join(latest_prices, and_(
                    latest_prices.c.product_id == Product.id,
                    latest_prices.c.rn == 1,
                ))
                .group_by(Category.name)
                .order_by(Category.name)
                .all()
            )

            if not results:
                return pd.DataFrame()

            df = pd.DataFrame(results, columns=[
                "category_name", "product_count", "avg_price",
                "min_price", "max_price", "avg_discount_pct",
            ])

            for col in ["avg_price", "min_price", "max_price"]:
                df[col] = df[col].round(2)
            df["avg_discount_pct"] = df["avg_discount_pct"].round(2)

            return df

        return self._execute_query(_query, session)

    # ---
    # Helper: Ejecutar query con manejo de sesión
    # ---
    def _execute_query(
        self,
        query_fn: Any,
        session: Session | None = None,
    ) -> pd.DataFrame:
        """Ejecuta query con sesión existente o crea una nueva."""
        if session is not None:
            try:
                return query_fn(session)
            except Exception as e:
                logger.error(f"Error ejecutando query: {type(e).__name__}: {e}")
                return pd.DataFrame()

        try:
            with get_session() as session:
                return query_fn(session)
        except Exception as e:
            logger.error(
                f"Error de BD ejecutando query: {type(e).__name__}: {e}"
            )
            return pd.DataFrame()

    # ---
    # 9. Price Changes — Datos de variaciones para histograma
    # ---
    def get_price_changes(
        self,
        days: int | None = None,
        category_id: int | None = None,
        session: Session | None = None,
    ) -> pd.DataFrame:
        """Variaciones porcentuales de precio (para histogramas)."""
        if days is None:
            days = self._default_days

        logger.info(f"Consultando variaciones de precio: days={days}")

        def _query(session: Session) -> pd.DataFrame:
            since = datetime.now(timezone.utc) - timedelta(days=days)

            query = (
                session.query(
                    Product.name.label("product_name"),
                    Store.name.label("store_name"),
                    Category.name.label("category_name"),
                    PriceHistory.price_change_pct,
                    PriceHistory.price,
                    PriceHistory.scraped_at,
                )
                .join(Product, PriceHistory.product_id == Product.id)
                .join(Store, Product.store_id == Store.id)
                .join(Category, Product.category_id == Category.id)
                .filter(
                    and_(
                        PriceHistory.scraped_at >= since,
                        PriceHistory.price_change_pct.isnot(None),
                    )
                )
            )

            if category_id:
                query = query.filter(Product.category_id == category_id)

            results = query.order_by(
                PriceHistory.scraped_at.desc()
            ).all()

            if not results:
                return pd.DataFrame()

            return pd.DataFrame(results, columns=[
                "product_name", "store_name", "category_name",
                "price_change_pct", "price", "scraped_at",
            ])

        return self._execute_query(_query, session)

    # ---
    # 10. Products List — Productos con filtros
    # ---
    def get_products_list(
        self,
        category_id: int | None = None,
        session: Session | None = None,
    ) -> pd.DataFrame:
        """Lista de productos con categoría y tienda (para filtros del dashboard)."""
        logger.info(f"Consultando lista de productos: category_id={category_id}")

        def _query(session: Session) -> pd.DataFrame:
            query = (
                session.query(
                    Product.id,
                    Product.name,
                    Product.brand,
                    Product.category_id,
                    Category.name.label("category_name"),
                    Product.store_id,
                    Store.name.label("store_name"),
                )
                .join(Category, Product.category_id == Category.id)
                .join(Store, Product.store_id == Store.id)
            )

            if category_id:
                query = query.filter(Product.category_id == category_id)

            results = query.order_by(
                Category.name, Product.name
            ).all()

            if not results:
                return pd.DataFrame()

            return pd.DataFrame(results, columns=[
                "id", "name", "brand", "category_id",
                "category_name", "store_id", "store_name",
            ])

        return self._execute_query(_query, session)

    # ---
    # 11. Category Price Stats — Datos para boxplot por categoría
    # ---
    def get_category_price_stats(
        self,
        days: int | None = None,
        session: Session | None = None,
    ) -> pd.DataFrame:
        """Precios por categoría para boxplot."""
        if days is None:
            days = self._default_days

        logger.info(f"Consultando stats de precio por categoría: days={days}")

        def _query(session: Session) -> pd.DataFrame:
            since = datetime.now(timezone.utc) - timedelta(days=days)

            # Subquery: último precio por producto
            latest_prices = (
                session.query(
                    PriceHistory.product_id,
                    PriceHistory.price,
                    func.row_number().over(
                        partition_by=PriceHistory.product_id,
                        order_by=desc(PriceHistory.scraped_at),
                    ).label("rn"),
                )
                .filter(PriceHistory.scraped_at >= since)
                .subquery()
            )

            results = (
                session.query(
                    Category.name.label("category_name"),
                    Product.name.label("product_name"),
                    Store.name.label("store_name"),
                    latest_prices.c.price,
                )
                .join(Product, latest_prices.c.product_id == Product.id)
                .join(Category, Product.category_id == Category.id)
                .join(Store, Product.store_id == Store.id)
                .filter(latest_prices.c.rn == 1)
                .order_by(Category.name, latest_prices.c.price)
                .all()
            )

            if not results:
                return pd.DataFrame()

            return pd.DataFrame(results, columns=[
                "category_name", "product_name", "store_name", "price",
            ])

        return self._execute_query(_query, session)

    # ---
    # 12. Store Category Comparison — Precio promedio por categoría y tienda
    # ---
    def get_store_category_comparison(
        self,
        session: Session | None = None,
    ) -> pd.DataFrame:
        """Precio promedio por categoría × tienda (para barras agrupadas)."""
        logger.info("Consultando comparación categoría×tienda...")

        def _query(session: Session) -> pd.DataFrame:
            # Subquery: último precio por producto
            latest_prices = (
                session.query(
                    PriceHistory.product_id,
                    PriceHistory.price,
                    func.row_number().over(
                        partition_by=PriceHistory.product_id,
                        order_by=desc(PriceHistory.scraped_at),
                    ).label("rn"),
                )
                .subquery()
            )

            results = (
                session.query(
                    Category.name.label("category_name"),
                    Store.name.label("store_name"),
                    func.avg(latest_prices.c.price).label("avg_price"),
                    func.count(Product.id).label("product_count"),
                )
                .join(Product, Product.category_id == Category.id)
                .join(Store, Product.store_id == Store.id)
                .join(latest_prices, and_(
                    latest_prices.c.product_id == Product.id,
                    latest_prices.c.rn == 1,
                ))
                .group_by(Category.name, Store.name)
                .order_by(Category.name, Store.name)
                .all()
            )

            if not results:
                return pd.DataFrame()

            df = pd.DataFrame(results, columns=[
                "category_name", "store_name", "avg_price", "product_count",
            ])

            df["avg_price"] = df["avg_price"].round(2)

            return df

        return self._execute_query(_query, session)

    # ---
    # 13. Store Detailed Stats — Estadísticas detalladas por tienda
    # ---
    def get_store_detailed_stats(
        self,
        session: Session | None = None,
    ) -> pd.DataFrame:
        """Stats detalladas por tienda (precio, productos, última actualización)."""
        logger.info("Consultando estadísticas detalladas por tienda...")

        def _query(session: Session) -> pd.DataFrame:
            # Subquery: último precio por producto
            latest_prices = (
                session.query(
                    PriceHistory.product_id,
                    PriceHistory.price,
                    PriceHistory.scraped_at,
                    func.row_number().over(
                        partition_by=PriceHistory.product_id,
                        order_by=desc(PriceHistory.scraped_at),
                    ).label("rn"),
                )
                .subquery()
            )

            results = (
                session.query(
                    Store.name.label("store_name"),
                    func.avg(latest_prices.c.price).label("avg_price"),
                    func.min(latest_prices.c.price).label("min_price"),
                    func.max(latest_prices.c.price).label("max_price"),
                    func.count(Product.id).label("product_count"),
                    func.count(func.distinct(Product.category_id)).label("category_count"),
                    func.max(latest_prices.c.scraped_at).label("last_update"),
                )
                .join(Product, Product.store_id == Store.id)
                .join(latest_prices, and_(
                    latest_prices.c.product_id == Product.id,
                    latest_prices.c.rn == 1,
                ))
                .group_by(Store.name)
                .order_by(func.avg(latest_prices.c.price).asc())
                .all()
            )

            if not results:
                return pd.DataFrame()

            df = pd.DataFrame(results, columns=[
                "store_name", "avg_price", "min_price", "max_price",
                "product_count", "category_count", "last_update",
            ])

            for col in ["avg_price", "min_price", "max_price"]:
                df[col] = df[col].round(2)

            return df

        return self._execute_query(_query, session)

    # ---
    # 14. Most Volatile Products — Productos más volátiles por categoría
    # ---
    def get_most_volatile_products(
        self,
        category_id: int,
        top_n: int = 5,
        days: int | None = None,
        session: Session | None = None,
    ) -> pd.DataFrame:
        """Top N productos más volátiles de una categoría."""
        if days is None:
            days = self._default_days

        logger.info(
            f"Consultando top {top_n} productos más volátiles: "
            f"category_id={category_id}, days={days}"
        )

        def _query(session: Session) -> pd.DataFrame:
            since = datetime.now(timezone.utc) - timedelta(days=days)

            # Subquery: último precio por producto
            latest_prices = (
                session.query(
                    PriceHistory.product_id,
                    PriceHistory.price.label("current_price"),
                    func.row_number().over(
                        partition_by=PriceHistory.product_id,
                        order_by=desc(PriceHistory.scraped_at),
                    ).label("rn"),
                )
                .subquery()
            )

            # Query principal: volatilidad por producto
            results = (
                session.query(
                    Product.id.label("product_id"),
                    Product.name.label("product_name"),
                    Store.name.label("store_name"),
                    _dialect_stddev(PriceHistory.price_change_pct).label("volatility"),
                    func.avg(PriceHistory.price_change_pct).label("avg_change_pct"),
                    func.count(PriceHistory.id).label("price_records"),
                    latest_prices.c.current_price,
                )
                .join(Store, Product.store_id == Store.id)
                .join(
                    PriceHistory,
                    PriceHistory.product_id == Product.id,
                )
                .join(
                    latest_prices,
                    and_(
                        latest_prices.c.product_id == Product.id,
                        latest_prices.c.rn == 1,
                    ),
                )
                .filter(
                    and_(
                        Product.category_id == category_id,
                        PriceHistory.scraped_at >= since,
                        PriceHistory.price_change_pct.isnot(None),
                    )
                )
                .group_by(
                    Product.id, Product.name, Store.name,
                    latest_prices.c.current_price,
                )
                .order_by(
                    _dialect_stddev(PriceHistory.price_change_pct).desc()
                )
                .limit(top_n)
                .all()
            )

            if not results:
                return pd.DataFrame()

            df = pd.DataFrame(results, columns=[
                "product_id", "product_name", "store_name",
                "volatility", "avg_change_pct", "price_records",
                "current_price",
            ])

            df["volatility"] = df["volatility"].round(4)
            df["avg_change_pct"] = df["avg_change_pct"].round(2)
            df["current_price"] = df["current_price"].round(2)

            return df

        return self._execute_query(_query, session)

    # ---
    # 15. Product Detail — Detalle de un producto con historial
    # ---
    def get_product_detail(
        self,
        product_id: int,
        days: int | None = None,
        session: Session | None = None,
    ) -> pd.DataFrame:
        """Historial de precios de un producto."""
        if days is None:
            days = self._default_days

        logger.info(
            f"Consultando detalle de producto: product_id={product_id}, days={days}"
        )

        def _query(session: Session) -> pd.DataFrame:
            since = datetime.now(timezone.utc) - timedelta(days=days)

            results = (
                session.query(
                    PriceHistory.scraped_at.label("date"),
                    PriceHistory.price,
                    PriceHistory.availability,
                    PriceHistory.price_change,
                    PriceHistory.price_change_pct,
                )
                .filter(
                    and_(
                        PriceHistory.product_id == product_id,
                        PriceHistory.scraped_at >= since,
                    )
                )
                .order_by(PriceHistory.scraped_at.asc())
                .all()
            )

            if not results:
                return pd.DataFrame()

            df = pd.DataFrame(results, columns=[
                "date", "price", "availability",
                "price_change", "price_change_pct",
            ])

            df["price"] = df["price"].round(2)

            return df

        return self._execute_query(_query, session)


# ---
# Exportación
# ---
__all__ = ["AnalyticsService"]
