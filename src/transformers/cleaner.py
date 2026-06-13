"""Limpieza y normalización de datos crudos del scraper."""

import re
from typing import Any

import pandas as pd
from loguru import logger

from src.config import Categories, PriceValidation, Stores, settings
from src.scrapers.base_scraper import ScrapeResult


# ---
# Mapeos nombre → ID
# ---
CATEGORY_ID_MAP: dict[str, int] = {
    Categories.CPU: 1,
    Categories.GPU: 2,
    Categories.RAM: 3,
    Categories.SSD: 4,
    Categories.LAPTOP: 5,
    Categories.MONITOR: 6,
    Categories.MOTHERBOARD: 7,
}

STORE_ID_MAP: dict[str, int] = {
    Stores.MERCADO_LIBRE: 1,
    Stores.ALIEXPRESS: 2,
    Stores.TEMU: 3,
}

# Variaciones de nombres de categorías que los scrapers pueden retornar
CATEGORY_ALIASES: dict[str, str] = {
    "cpu": Categories.CPU,
    "procesador": Categories.CPU,
    "processors": Categories.CPU,
    "gpu": Categories.GPU,
    "grafica": Categories.GPU,
    "graphics card": Categories.GPU,
    "ram": Categories.RAM,
    "memoria ram": Categories.RAM,
    "memory": Categories.RAM,
    "ssd": Categories.SSD,
    "disco solido": Categories.SSD,
    "storage": Categories.SSD,
    "laptop": Categories.LAPTOP,
    "laptops": Categories.LAPTOP,
    "notebook": Categories.LAPTOP,
    "computadora": Categories.LAPTOP,
    "monitor": Categories.MONITOR,
    "monitores": Categories.MONITOR,
    "display": Categories.MONITOR,
    "pantalla": Categories.MONITOR,
    "motherboard": Categories.MOTHERBOARD,
    "placa madre": Categories.MOTHERBOARD,
    "placas madre": Categories.MOTHERBOARD,
    "mainboard": Categories.MOTHERBOARD,
    "tarjeta madre": Categories.MOTHERBOARD,
}

# Variaciones comunes de nombres de tiendas
STORE_ALIASES: dict[str, str] = {
    "mercadolibre": Stores.MERCADO_LIBRE,
    "mercado libre": Stores.MERCADO_LIBRE,
    "mercado_libre": Stores.MERCADO_LIBRE,
    "ml": Stores.MERCADO_LIBRE,
    "aliexpress": Stores.ALIEXPRESS,
    "ali_express": Stores.ALIEXPRESS,
    "ae": Stores.ALIEXPRESS,
    "temu": Stores.TEMU,
}


class DataCleaner:
    """Limpia y normaliza datos crudos para inserción en BD."""

    def __init__(self, usd_to_mxn: float | None = None) -> None:
        """Inicializa el cleaner. Si no pasas usd_to_mxn, usa settings."""
        self._usd_to_mxn: float = usd_to_mxn or settings.currency.usd_to_mxn
        self._stats: dict[str, int] = {
            "rows_input": 0,
            "rows_after_normalize": 0,
            "rows_after_category_map": 0,
            "rows_after_store_map": 0,
            "rows_after_currency": 0,
            "rows_after_dedup": 0,
            "rows_after_validation": 0,
            "rows_output": 0,
            "prices_converted": 0,
            "duplicates_removed": 0,
            "invalid_prices": 0,
            "unmapped_categories": 0,
            "unmapped_stores": 0,
        }

        logger.info(
            f"DataCleaner inicializado — USD/MXN: {self._usd_to_mxn}, "
            f"moneda base: {settings.currency.base_currency}"
        )

    # ---
    # Propiedades
    # ---
    @property
    def usd_to_mxn(self) -> float:
        """Tipo de cambio USD → MXN actual."""
        return self._usd_to_mxn

    @property
    def stats(self) -> dict[str, int]:
        """Métricas de la última ejecución de limpieza."""
        return self._stats.copy()

    # ---
    # Paso 0: Conversión de ScrapeResult → DataFrame
    # ---
    def to_dataframe(self, results: list[ScrapeResult]) -> pd.DataFrame:
        """Convierte lista de ScrapeResult a DataFrame."""
        if not results:
            logger.warning("Lista de ScrapeResult vacía — retornando DataFrame vacío")
            return pd.DataFrame()

        records = [r.to_dict() for r in results]
        df = pd.DataFrame(records)

        self._stats["rows_input"] = len(df)

        logger.info(f"ScrapeResult → DataFrame: {len(df)} filas, {len(df.columns)} columnas")
        return df

    # ---
    # Paso 1: Normalización de nombres
    # ---
    def normalize_names(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normaliza nombres: strip, colapsar espacios, quitar emojis, truncar."""
        if df.empty:
            return df

        df = df.copy()

        # 1. Strip
        df["name"] = df["name"].astype(str).str.strip()

        # 2. Colapsar múltiples espacios
        df["name"] = df["name"].str.replace(r"\s+", " ", regex=True)

        # 3. Eliminar caracteres de control (ASCII < 32 except tab/newline)
        df["name"] = df["name"].apply(self._remove_control_chars)

        # 4. Eliminar emojis y caracteres especiales (preservar acentos y ñ)
        df["name"] = df["name"].apply(self._remove_special_chars)

        # 5. Primera letra mayúscula
        df["name"] = df["name"].apply(
            lambda s: s[0].upper() + s[1:] if len(s) > 0 else s
        )

        # 6. Truncar a 300 caracteres
        df["name"] = df["name"].str.slice(0, 300)

        # 7. Eliminar filas sin nombre válido
        before = len(df)
        df = df[df["name"].str.len() > 0]
        removed = before - len(df)

        if removed > 0:
            logger.info(f"Normalización: {removed} filas sin nombre eliminadas")

        self._stats["rows_after_normalize"] = len(df)
        logger.info(f"Nombres normalizados: {len(df)} filas")
        return df

    # ---
    # Paso 2: Mapeo de categorías a IDs
    # ---
    def map_categories(self, df: pd.DataFrame) -> pd.DataFrame:
        """Mapea category → category_id. Busca primero exacto, luego aliases. Sin mapeo = eliminada."""
        if df.empty:
            return df

        df = df.copy()

        # Intentar mapeo directo
        df["category_id"] = df["category"].map(CATEGORY_ID_MAP)

        # Para los no mapeados, intentar con aliases (case-insensitive)
        unmapped_mask = df["category_id"].isna()
        if unmapped_mask.any():
            # Normalizar a minúsculas para buscar en aliases
            lower_categories = df.loc[unmapped_mask, "category"].str.lower().str.strip()
            df.loc[unmapped_mask, "category_id"] = lower_categories.map(
                lambda c: CATEGORY_ID_MAP.get(CATEGORY_ALIASES.get(c, ""))
            )

        # Estadísticas de mapeo
        still_unmapped = df["category_id"].isna().sum()
        self._stats["unmapped_categories"] = int(still_unmapped)

        if still_unmapped > 0:
            unmapped_names = df.loc[df["category_id"].isna(), "category"].unique().tolist()
            logger.warning(
                f"Categorías no mapeadas: {unmapped_names} "
                f"({still_unmapped} productos eliminados)"
            )

        # Eliminar filas sin categoría mapeada
        before = len(df)
        df = df.dropna(subset=["category_id"])
        df["category_id"] = df["category_id"].astype(int)
        removed = before - len(df)

        self._stats["rows_after_category_map"] = len(df)
        logger.info(
            f"Categorías mapeadas: {len(df)} filas "
            f"({removed} sin categoría eliminadas)"
        )
        return df

    # ---
    # Paso 3: Mapeo de tiendas a IDs
    # ---
    def map_stores(self, df: pd.DataFrame) -> pd.DataFrame:
        """Mapea store_name → store_id. Igual que categorías: exacto, luego aliases, sin mapeo = eliminada."""
        if df.empty:
            return df

        df = df.copy()

        # Intentar mapeo directo
        df["store_id"] = df["store_name"].map(STORE_ID_MAP)

        # Para los no mapeados, intentar con aliases (case-insensitive)
        unmapped_mask = df["store_id"].isna()
        if unmapped_mask.any():
            lower_stores = df.loc[unmapped_mask, "store_name"].str.lower().str.strip()
            df.loc[unmapped_mask, "store_id"] = lower_stores.map(
                lambda s: STORE_ID_MAP.get(STORE_ALIASES.get(s, ""))
            )

        # Estadísticas de mapeo
        still_unmapped = df["store_id"].isna().sum()
        self._stats["unmapped_stores"] = int(still_unmapped)

        if still_unmapped > 0:
            unmapped_names = df.loc[df["store_id"].isna(), "store_name"].unique().tolist()
            logger.warning(
                f"Tiendas no mapeadas: {unmapped_names} "
                f"({still_unmapped} productos eliminados)"
            )

        # Eliminar filas sin tienda mapeada
        before = len(df)
        df = df.dropna(subset=["store_id"])
        df["store_id"] = df["store_id"].astype(int)
        removed = before - len(df)

        self._stats["rows_after_store_map"] = len(df)
        logger.info(
            f"Tiendas mapeadas: {len(df)} filas "
            f"({removed} sin tienda eliminadas)"
        )
        return df

    # ---
    # Paso 4: Conversión de monedas
    # ---
    def convert_currencies(self, df: pd.DataFrame) -> pd.DataFrame:
        """Convierte USD→MXN, otra moneda = eliminada. Preserva price_original para debugging."""
        if df.empty:
            return df

        df = df.copy()

        # Preservar precio original para trazabilidad
        df["price_original"] = df["price"].copy()

        # Identificar filas por moneda
        usd_mask = df["currency"].str.upper() == "USD"
        mxn_mask = df["currency"].str.upper() == "MXN"
        other_mask = ~usd_mask & ~mxn_mask

        # Convertir USD → MXN
        converted_count = int(usd_mask.sum())
        if converted_count > 0:
            df.loc[usd_mask, "price"] = (
                df.loc[usd_mask, "price"] * self._usd_to_mxn
            ).round(2)
            df.loc[usd_mask, "currency"] = "MXN"
            logger.info(
                f"Conversión USD→MXN: {converted_count} precios convertidos "
                f"(rate: {self._usd_to_mxn})"
            )

        # Monedas no soportadas
        other_count = int(other_mask.sum())
        if other_count > 0:
            other_currencies = df.loc[other_mask, "currency"].unique().tolist()
            logger.warning(
                f"Monedas no soportadas: {other_currencies} "
                f"({other_count} productos eliminados)"
            )
            df = df[~other_mask]

        self._stats["prices_converted"] = converted_count
        self._stats["rows_after_currency"] = len(df)
        logger.info(
            f"Conversión de monedas: {len(df)} filas "
            f"({converted_count} USD→MXN, {other_count} eliminadas)"
        )
        return df

    # ---
    # Paso 5: Eliminación de duplicados
    # ---
    def remove_duplicates(self, df: pd.DataFrame) -> pd.DataFrame:
        """Elimina duplicados por (name, store_id) y por URL. Conserva el más reciente/barato."""
        if df.empty:
            return df

        df = df.copy()
        before = len(df)

        # 1. Deduplicación por nombre + tienda (constraint de BD)
        # Ordenar por scraped_at descendente (más reciente primero)
        # y por precio ascendente (menor precio primero en caso de empate)
        df = df.sort_values(
            ["name", "store_id", "scraped_at", "price"],
            ascending=[True, True, False, True],
        )

        # Mantener el primero (más reciente, menor precio en empate)
        df = df.drop_duplicates(subset=["name", "store_id"], keep="first")

        # 2. Deduplicación por URL (mismo producto, nombres diferentes)
        if "url" in df.columns:
            df_with_url = df[df["url"].notna() & (df["url"] != "")]

            if len(df_with_url) > 0:
                # Para productos con la misma URL en la misma tienda
                df_with_url = df_with_url.sort_values(
                    ["url", "store_id", "scraped_at"],
                    ascending=[True, True, False],
                )
                url_dupes = df_with_url.drop_duplicates(
                    subset=["url", "store_id"], keep="first"
                )

                # Combinar: productos sin URL + deduplicados con URL
                df_no_url = df[df["url"].isna() | (df["url"] == "")]
                df = pd.concat([df_no_url, url_dupes], ignore_index=True)

        duplicates_removed = before - len(df)
        self._stats["duplicates_removed"] = duplicates_removed
        self._stats["rows_after_dedup"] = len(df)

        if duplicates_removed > 0:
            logger.info(
                f"Deduplicación: {duplicates_removed} duplicados eliminados "
                f"({before} → {len(df)})"
            )
        else:
            logger.info("Deduplicación: sin duplicados encontrados")

        return df

    # ---
    # Paso 6: Validación de precios
    # ---
    def validate_prices(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filtra precios fuera de rango por categoría y precios <= 0."""
        if df.empty:
            return df

        df = df.copy()
        before = len(df)

        # 1. Eliminar precios <= 0
        invalid_zero = int((df["price"] <= 0).sum())
        if invalid_zero > 0:
            logger.info(f"Validación: {invalid_zero} productos con precio <= 0 eliminados")
            df = df[df["price"] > 0]

        # 2. Validar rangos por categoría
        invalid_range_count = 0
        invalid_details: list[str] = []

        # Mapeo inverso: category_id → nombre de categoría para buscar rangos
        id_to_category = {v: k for k, v in CATEGORY_ID_MAP.items()}

        for cat_id, cat_name in id_to_category.items():
            cat_mask = df["category_id"] == cat_id
            if not cat_mask.any():
                continue

            cat_range = PriceValidation.RANGES.get(cat_name)
            if cat_range is None:
                continue

            price_min, price_max = cat_range

            # Filtrar precios fuera de rango
            out_of_range = cat_mask & (
                (df["price"] < price_min) | (df["price"] > price_max)
            )
            count = int(out_of_range.sum())

            if count > 0:
                invalid_range_count += count
                # Recopilar detalles para logging
                invalid_prices = df.loc[out_of_range, "price"].tolist()
                invalid_names = df.loc[out_of_range, "name"].head(3).tolist()
                detail = (
                    f"  {cat_name}: {count} fuera de rango "
                    f"[{price_min:,.0f}-{price_max:,.0f}] — "
                    f"ej: {invalid_names[0][:40]} ${invalid_prices[0]:,.2f}"
                )
                invalid_details.append(detail)
                df = df[~out_of_range]

        # Log detallado de precios inválidos
        if invalid_details:
            logger.warning(
                f"Precios fuera de rango ({invalid_range_count} total):\n"
                + "\n".join(invalid_details)
            )

        total_invalid = invalid_zero + invalid_range_count
        self._stats["invalid_prices"] = total_invalid
        self._stats["rows_after_validation"] = len(df)

        logger.info(
            f"Validación de precios: {len(df)} filas válidas "
            f"({total_invalid} eliminadas: {invalid_zero} sin precio, "
            f"{invalid_range_count} fuera de rango)"
        )
        return df

    # ---
    # Pipeline completo
    # ---
    def clean_all(self, results: list[ScrapeResult]) -> pd.DataFrame:
        """Ejecuta todo el pipeline: to_df → normalize → map → convert → dedup → validate."""
        logger.info(f"Iniciando pipeline de limpieza: {len(results)} productos crudos")

        # Reset stats
        self._stats = {k: 0 for k in self._stats}

        # Ejecutar pipeline
        df = self.to_dataframe(results)
        df = self.normalize_names(df)
        df = self.map_categories(df)
        df = self.map_stores(df)
        df = self.convert_currencies(df)
        df = self.remove_duplicates(df)
        df = self.validate_prices(df)

        # Reset index para DataFrame limpio
        df = df.reset_index(drop=True)

        # Stats finales
        self._stats["rows_output"] = len(df)

        logger.info(
            f"Pipeline de limpieza completado: "
            f"{self._stats['rows_input']} → {len(df)} filas "
            f"({self._stats['duplicates_removed']} duplicados, "
            f"{self._stats['invalid_prices']} precios inválidos, "
            f"{self._stats['prices_converted']} USD→MXN)"
        )

        return df

    # ---
    # Helpers privados
    # ---
    @staticmethod
    def _remove_control_chars(text: str) -> str:
        """Elimina chars de control (ASCII < 32) excepto espacio."""
        return "".join(c for c in text if ord(c) >= 32 or c == " ")

    @staticmethod
    def _remove_special_chars(text: str) -> str:
        """Elimina emojis y chars especiales, preserva acentos/ñ."""
        # Patrón: mantener letras latinas, números, puntuación básica y símbolos de productos
        # Rangos Unicode:
        #   \u00C0-\u024F = Latin Extended (incluye acentos, ñ)
        #   \u2000-\u206F = General Punctuation (guiones, comillas)
        #   \u0020-\u007E = ASCII básico
        pattern = r"[^\u0020-\u007E\u00C0-\u024F\u2000-\u206F\-+/.()]"
        return re.sub(pattern, "", text)


# ---
# Exportación
# ---
__all__ = [
    "DataCleaner",
    "CATEGORY_ID_MAP",
    "STORE_ID_MAP",
    "CATEGORY_ALIASES",
    "STORE_ALIASES",
]
