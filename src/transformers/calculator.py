"""Cálculo de variaciones de precio — price_change y price_change_pct."""

from datetime import datetime
from typing import Any

import pandas as pd
from loguru import logger
from sqlalchemy import Float, and_, func
from sqlalchemy.orm import Session

from src.database.models import PriceHistory, Product
from src.transformers.cleaner import CATEGORY_ID_MAP


class PriceCalculator:
    """Calcula variaciones de precio — modo DataFrame o modo BD."""

    def __init__(self) -> None:
        """Inicializa el calculator."""
        self._stats: dict[str, int] = {
            "products_processed": 0,
            "changes_calculated": 0,
            "first_records": 0,         # Productos sin registro anterior
            "price_increases": 0,       # Productos con aumento de precio
            "price_decreases": 0,       # Productos con baja de precio
            "price_unchanged": 0,       # Productos con precio sin cambio
            "db_queries": 0,            # Consultas a BD realizadas
        }

        logger.info("PriceCalculator inicializado")

    # ---
    # Propiedades
    # ---
    @property
    def stats(self) -> dict[str, int]:
        """Stats de la última ejecución."""
        return self._stats.copy()

    # ---
    # Modo 1: Cálculo sobre DataFrame (sin BD)
    # ---
    def calculate_changes(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calcula variaciones dentro de un DataFrame (groupby diff). Primer registro = None."""
        if df.empty:
            logger.warning("DataFrame vacío — retornando sin cambios")
            return df

        df = df.copy()
        self._stats = {k: 0 for k in self._stats}

        # Ordenar por producto y fecha
        df = df.sort_values(
            ["name", "store_id", "scraped_at"],
            ascending=[True, True, True],
        )

        # Calcular cambio absoluto y porcentual por grupo de producto
        # Un producto único = (name, store_id)
        df["price_change"] = df.groupby(["name", "store_id"])["price"].diff()
        df["price_change_pct"] = df.groupby(["name", "store_id"])["price"].pct_change() * 100

        # Redondear para evitar decimales excesivos
        df["price_change"] = df["price_change"].round(2)
        df["price_change_pct"] = df["price_change_pct"].round(2)

        # Estadísticas
        self._stats["products_processed"] = len(df)
        self._stats["changes_calculated"] = int(df["price_change"].notna().sum())
        self._stats["first_records"] = int(df["price_change"].isna().sum())
        self._stats["price_increases"] = int((df["price_change"] > 0).sum())
        self._stats["price_decreases"] = int((df["price_change"] < 0).sum())
        self._stats["price_unchanged"] = int((df["price_change"] == 0).sum())

        logger.info(
            f"Variaciones calculadas (DataFrame): "
            f"{self._stats['changes_calculated']} cambios, "
            f"{self._stats['first_records']} primeros registros, "
            f"{self._stats['price_increases']} ↑, "
            f"{self._stats['price_decreases']} ↓, "
            f"{self._stats['price_unchanged']} ="
        )

        return df

    # ---
    # Modo 2: Cálculo vs último registro en BD
    # ---
    def calculate_changes_vs_db(
        self, df: pd.DataFrame, session: Session
    ) -> pd.DataFrame:
        """Calcula variaciones vs último registro en BD. Más preciso que calculate_changes()."""
        if df.empty:
            logger.warning("DataFrame vacío — retornando sin cambios")
            return df

        df = df.copy()
        self._stats = {k: 0 for k in self._stats}

        # Inicializar columnas
        df["price_change"] = None
        df["price_change_pct"] = None

        # Obtener IDs de productos existentes en BD por (name, store_id)
        # Usar una sola query para eficiencia
        product_pairs = df[["name", "store_id"]].drop_duplicates()

        for _, row in product_pairs.iterrows():
            product_name = row["name"]
            store_id = row["store_id"]

            # Buscar el producto en BD
            product = session.query(Product).filter(
                and_(
                    Product.name == product_name,
                    Product.store_id == store_id,
                )
            ).first()

            if product is None:
                # Producto nuevo — sin registro anterior
                continue

            # Obtener el último precio registrado
            last_price_record = session.query(PriceHistory).filter(
                PriceHistory.product_id == product.id
            ).order_by(PriceHistory.scraped_at.desc()).first()

            if last_price_record is None:
                # Producto sin historial — primer registro
                continue

            self._stats["db_queries"] += 1

            # Calcular variación
            previous_price = last_price_record.price
            current_price = df.loc[
                (df["name"] == product_name) & (df["store_id"] == store_id),
                "price"
            ].iloc[0]

            price_change = round(current_price - previous_price, 2)

            if previous_price != 0:
                price_change_pct = round(
                    ((current_price - previous_price) / previous_price) * 100, 2
                )
            else:
                price_change_pct = None  # No se puede calcular % con precio 0

            # Asignar al DataFrame
            mask = (df["name"] == product_name) & (df["store_id"] == store_id)
            df.loc[mask, "price_change"] = price_change
            df.loc[mask, "price_change_pct"] = price_change_pct

        # Estadísticas
        self._stats["products_processed"] = len(df)
        self._stats["changes_calculated"] = int(df["price_change"].notna().sum())
        self._stats["first_records"] = int(df["price_change"].isna().sum())
        self._stats["price_increases"] = int((df["price_change"] > 0).sum())
        self._stats["price_decreases"] = int((df["price_change"] < 0).sum())
        self._stats["price_unchanged"] = int((df["price_change"] == 0).sum())

        logger.info(
            f"Variaciones calculadas (vs BD): "
            f"{self._stats['changes_calculated']} cambios, "
            f"{self._stats['first_records']} primeros registros, "
            f"{self._stats['db_queries']} queries BD, "
            f"{self._stats['price_increases']} ↑, "
            f"{self._stats['price_decreases']} ↓, "
            f"{self._stats['price_unchanged']} ="
        )

        return df

    # ---
    # Modo 3: Cálculo optimizado con query masiva (batch)
    # ---
    def calculate_changes_batch(
        self, df: pd.DataFrame, session: Session
    ) -> pd.DataFrame:
        """Calcula variaciones con una sola query masiva (más eficiente para >50 productos)."""
        if df.empty:
            return df

        df = df.copy()
        self._stats = {k: 0 for k in self._stats}

        # Inicializar columnas
        df["price_change"] = None
        df["price_change_pct"] = None

        # Query masiva: obtener el último precio de cada producto
        # que coincida con (name, store_id) del DataFrame
        product_pairs = df[["name", "store_id"]].drop_duplicates()

        # Subquery: último precio por producto (usando window function)
        # SQLAlchemy equivalent of:
        #   SELECT ph.product_id, ph.price, p.name, p.store_id
        #   FROM price_history ph
        #   JOIN products p ON ph.product_id = p.id
        #   WHERE (p.name, p.store_id) IN (product_pairs)
        #   AND ph.scraped_at = (
        #       SELECT MAX(scraped_at) FROM price_history
        #       WHERE product_id = ph.product_id
        #   )

        # Obtener productos existentes en BD que coinciden con nuestro DataFrame
        from sqlalchemy import tuple_

        # Construir lista de condiciones OR para los pares (name, store_id)
        conditions = []
        for _, row in product_pairs.iterrows():
            conditions.append(
                and_(
                    Product.name == row["name"],
                    Product.store_id == int(row["store_id"]),
                )
            )

        if not conditions:
            logger.info("Sin productos para comparar con BD")
            self._stats["products_processed"] = len(df)
            self._stats["first_records"] = len(df)
            return df

        # Query: productos que existen en BD
        existing_products = session.query(Product).filter(
            or_conditions(conditions)  # type: ignore
        ).all()

        self._stats["db_queries"] = 1  # Una sola query

        if not existing_products:
            logger.info("Ningún producto encontrado en BD — todos son primeros registros")
            self._stats["products_processed"] = len(df)
            self._stats["first_records"] = len(df)
            return df

        # Obtener último precio de cada producto existente
        product_last_prices: dict[tuple[str, int], float] = {}

        for product in existing_products:
            last_record = session.query(PriceHistory).filter(
                PriceHistory.product_id == product.id
            ).order_by(PriceHistory.scraped_at.desc()).first()

            if last_record:
                product_last_prices[(product.name, product.store_id)] = last_record.price

        # Calcular variaciones usando los datos obtenidos
        for (name, store_id), previous_price in product_last_prices.items():
            mask = (df["name"] == name) & (df["store_id"] == store_id)

            if not mask.any():
                continue

            current_price = df.loc[mask, "price"].iloc[0]
            price_change = round(current_price - previous_price, 2)

            if previous_price != 0:
                price_change_pct = round(
                    ((current_price - previous_price) / previous_price) * 100, 2
                )
            else:
                price_change_pct = None

            df.loc[mask, "price_change"] = price_change
            df.loc[mask, "price_change_pct"] = price_change_pct

        # Estadísticas
        self._stats["products_processed"] = len(df)
        self._stats["changes_calculated"] = int(df["price_change"].notna().sum())
        self._stats["first_records"] = int(df["price_change"].isna().sum())
        self._stats["price_increases"] = int((df["price_change"] > 0).sum())
        self._stats["price_decreases"] = int((df["price_change"] < 0).sum())
        self._stats["price_unchanged"] = int((df["price_change"] == 0).sum())

        logger.info(
            f"Variaciones calculadas (batch): "
            f"{self._stats['changes_calculated']} cambios, "
            f"{self._stats['first_records']} primeros registros, "
            f"{self._stats['price_increases']} ↑, "
            f"{self._stats['price_decreases']} ↓, "
            f"{self._stats['price_unchanged']} ="
        )

        return df

    # ---
    # Helper: Calcular cambio para un producto individual
    # ---
    @staticmethod
    def compute_change(
        current_price: float, previous_price: float | None
    ) -> tuple[float | None, float | None]:
        """Calcula (price_change, price_change_pct) para un producto. previous_price=None → (None, None)."""
        if previous_price is None:
            return None, None

        price_change = round(current_price - previous_price, 2)

        if previous_price == 0:
            return price_change, None

        price_change_pct = round(
            ((current_price - previous_price) / previous_price) * 100, 2
        )

        return price_change, price_change_pct

    # ---
    # Helper: Obtener último precio de un producto desde BD
    # ---
    @staticmethod
    def get_last_price(
        session: Session, product_id: int
    ) -> float | None:
        """Último precio registrado de un producto, o None."""
        last_record = session.query(PriceHistory).filter(
            PriceHistory.product_id == product_id
        ).order_by(PriceHistory.scraped_at.desc()).first()

        return last_record.price if last_record else None


# ---
# Helper: Construir condición OR desde lista de condiciones
# ---
def or_conditions(conditions: list) -> Any:
    """Construye condición OR desde lista de condiciones SQLAlchemy."""
    from sqlalchemy import or_

    if not conditions:
        return False  # type: ignore
    if len(conditions) == 1:
        return conditions[0]
    return or_(*conditions)


# ---
# Exportación
# ---
__all__ = ["PriceCalculator"]
