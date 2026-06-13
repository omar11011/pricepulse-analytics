"""
Módulo de Transformación.

Responsabilidades:
    - Normalizar nombres de productos
    - Mapear categorías y tiendas a IDs de la base de datos
    - Convertir monedas (USD → MXN)
    - Eliminar duplicados y registros inválidos
    - Validar rangos de precio por categoría
    - Calcular variaciones de precio (price_change, price_change_pct)

Componentes:
    - DataCleaner: Pipeline de limpieza y normalización
    - PriceCalculator: Cálculo de variaciones de precio vs registro anterior

Uso rápido:
    from src.transformers import DataCleaner, PriceCalculator

    cleaner = DataCleaner()
    clean_df = cleaner.clean_all(scrape_results)

    calculator = PriceCalculator()
    df_with_changes = calculator.calculate_changes(clean_df)
"""

from src.transformers.cleaner import (
    DataCleaner,
    CATEGORY_ID_MAP,
    STORE_ID_MAP,
    CATEGORY_ALIASES,
    STORE_ALIASES,
)
from src.transformers.calculator import PriceCalculator

__all__ = [
    # Cleaner
    "DataCleaner",
    "CATEGORY_ID_MAP",
    "STORE_ID_MAP",
    "CATEGORY_ALIASES",
    "STORE_ALIASES",
    # Calculator
    "PriceCalculator",
]
