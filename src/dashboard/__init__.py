"""
Módulo de Dashboard (Streamlit).

Responsabilidades:
    - Renderizar la interfaz de usuario interactiva
    - Mostrar KPIs, gráficos y tablas
    - Proveer filtros dinámicos por categoría, tienda y fecha
    - Permitir ejecución manual del pipeline

Páginas:
    - Inicio:       KPIs y resumen general
    - Tendencias:   Evolución histórica de precios
    - Tiendas:      Ranking y comparación de tiendas
    - Componentes:  Detalle por categoría

Componentes:
    - app.py: Aplicación Streamlit principal

Uso:
    streamlit run src/dashboard/app.py
"""

__all__ = ["app"]
