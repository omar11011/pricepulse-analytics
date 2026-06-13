"""
Módulo de Pipeline (Orquestación ETL).

Responsabilidades:
    - Orquestar el flujo completo: scrape → transform → load
    - Ejecutar scrapers de forma secuencial con fallback
    - Aplicar transformaciones y validaciones
    - Insertar datos con upsert (inserción o actualización)
    - Deduplicar registros de precio (un registro por producto por día)
    - Generar logs de ejecución en pipeline_logs

Componentes:
    - PricePulsePipeline: Orquestador ETL principal
    - PipelineStatus: Constantes de status (success/partial_success/failure)
    - ScraperResult: Resultado de un scraper individual

Uso rápido:
    from src.pipeline import PricePulsePipeline

    pipeline = PricePulsePipeline()
    result = pipeline.run()
    print(result["status"], result["products_saved"])
"""

from src.pipeline.etl import PricePulsePipeline, PipelineStatus, ScraperResult

__all__ = [
    "PricePulsePipeline",
    "PipelineStatus",
    "ScraperResult",
]
