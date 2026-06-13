"""
Módulo de Analytics.

Responsabilidades:
    - Proveer consultas SQL que responden preguntas de negocio
    - Calcular métricas agregadas (KPIs, rankings, volatilidad)
    - Retornar DataFrames de Pandas para integración con Plotly

Métricas principales:
    - KPIs generales (productos monitoreados, precio promedio, descuentos)
    - Evolución histórica de precios
    - Ranking de tiendas por precio
    - Volatilidad de precios por categoría
    - Top descuentos
    - Mejor momento para comprar (análisis por día de semana)
    - Comparación de precios entre tiendas
    - Resumen por categoría

Componentes:
    - AnalyticsService: Servicio de consultas analíticas

Uso rápido:
    from src.analytics import AnalyticsService

    service = AnalyticsService()
    kpis = service.get_kpi_summary()
    ranking = service.get_store_ranking()
"""

from src.analytics.queries import AnalyticsService

__all__ = ["AnalyticsService"]
