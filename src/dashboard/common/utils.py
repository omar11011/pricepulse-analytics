"""Helpers: servicio de analytics, auto-seed, pipeline, sidebar."""

from datetime import datetime, timezone
from typing import Any

import streamlit as st
from loguru import logger

from src.analytics.queries import AnalyticsService
from src.config import Categories, Stores, settings
from src.dashboard.common.styles import COLORS, STORE_STATUS_ICONS


def get_analytics_service() -> AnalyticsService:
    """Singleton del AnalyticsService guardado en session_state."""
    if "analytics_service" not in st.session_state:
        st.session_state.analytics_service = AnalyticsService()
    return st.session_state.analytics_service


def ensure_database_populated():
    """Si la BD esta vacia, corre el seed automaticamente.

    Esto es clave para Streamlit Cloud donde el filesystem se reinicia
    con cada deploy. En local con datos persistentes, esta funcion no hace nada.
    """
    if "db_populated" in st.session_state:
        return

    try:
        from src.database.connection import get_session
        from src.database.models import Product

        with get_session() as session:
            count = session.query(Product).count()

        if count > 0:
            st.session_state.db_populated = True
            return

        logger.info("BD vacia, corriendo auto-seed...")
        from scripts.seed_data import seed_all
        result = seed_all()
        st.session_state.db_populated = True
        logger.info(f"Auto-seed: {result.get('products', 0)} productos, {result.get('price_records', 0)} precios")
        st.cache_data.clear()

    except Exception as e:
        logger.error(f"Error en auto-seed: {type(e).__name__}: {e}")
        st.session_state.db_populated = False


def run_pipeline():
    """Ejecuta el pipeline ETL desde el dashboard."""
    with st.spinner("Ejecutando pipeline ETL... Puede tardar varios minutos."):
        try:
            from src.pipeline.etl import PricePulsePipeline
            pipeline = PricePulsePipeline()
            result = pipeline.run()
            st.session_state.pipeline_result = result
            st.cache_data.clear()
            st.success(f"Pipeline: {result['status']} — {result['products_saved']} productos guardados")
        except Exception as e:
            st.session_state.pipeline_result = {
                "status": "failure",
                "message": f"Error: {type(e).__name__}: {e}",
                "products_found": 0,
                "products_saved": 0,
                "products_failed": 0,
                "execution_time_ms": 0,
            }
            st.error(f"Error ejecutando pipeline: {e}")


def render_pipeline_result(result: dict[str, Any]):
    """Muestra el resultado de la ultima ejecucion del pipeline."""
    status = result.get("status", "unknown")
    status_map = {
        "success": ("pipeline-success", "✅ Exitoso"),
        "partial_success": ("pipeline-partial", "⚠️ Parcial"),
        "failure": ("pipeline-failure", "❌ Fallido"),
    }
    css_class, status_label = status_map.get(status, ("", f"❔ {status}"))

    saved = result.get("products_saved", 0)
    found = result.get("products_found", 0)
    failed = result.get("products_failed", 0)
    time_ms = result.get("execution_time_ms", 0)
    time_s = round(time_ms / 1000, 1) if time_ms else 0

    st.markdown(
        f'<div class="{css_class}">'
        f'<strong>{status_label}</strong><br>'
        f'<span style="font-size:0.8rem;">'
        f"Encontrados: {found} | Guardados: {saved} | "
        f"Fallidos: {failed} | Tiempo: {time_s}s"
        f'</span></div>',
        unsafe_allow_html=True,
    )


def render_sidebar() -> str:
    """Sidebar con navegacion, estado del sistema y boton de pipeline.

    Returns:
        Nombre de la pagina seleccionada.
    """
    with st.sidebar:
        st.markdown('<div class="sidebar-title">PricePulse Analytics</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="sidebar-subtitle">Monitoreo de precios de tecnologia en Mexico</div>',
            unsafe_allow_html=True,
        )

        st.markdown("---")
        st.markdown("### Navegacion")

        pages = {"Inicio": "🏠", "Tendencias": "📈", "Tiendas": "🏪", "Componentes": "🔧"}

        if "current_page" not in st.session_state:
            st.session_state.current_page = "Inicio"

        selected_page = st.session_state.current_page

        for page_name, icon in pages.items():
            if st.button(f"{icon}  {page_name}", key=f"nav_{page_name}", use_container_width=True):
                st.session_state.current_page = page_name
                st.rerun()

        st.markdown("---")

        # Tiendas
        st.markdown("### Tiendas monitoreadas")
        for store_name in Stores.ALL:
            icon = STORE_STATUS_ICONS.get(store_name, "🟢")
            st.markdown(f"{icon} **{store_name}**")

        st.markdown("---")

        # Pipeline
        st.markdown("### Pipeline ETL")
        st.markdown(
            '<div style="font-size:0.8rem;color:#90A4AE;margin-bottom:0.5rem;">'
            'Ejecuta el scraping de las 3 tiendas</div>',
            unsafe_allow_html=True,
        )

        if st.button("▶ Ejecutar Pipeline", key="run_pipeline", use_container_width=True):
            run_pipeline()

        if "pipeline_result" in st.session_state:
            render_pipeline_result(st.session_state.pipeline_result)

        st.markdown("---")

        # Info del sistema
        st.markdown("### Informacion del sistema")
        st.markdown(
            f'<div style="font-size:0.75rem;color:#90A4AE;">'
            f"BD: `{settings.database.dialect_name.upper()}`<br>"
            f"Moneda: MXN<br>"
            f"USD/MXN: {settings.currency.usd_to_mxn}<br>"
            f"Categorias: {len(Categories.ALL)}"
            f'</div>',
            unsafe_allow_html=True,
        )

        st.markdown("---")
        st.markdown(
            '<div style="text-align:center;font-size:0.7rem;color:#607D8B;">'
            f'PricePulse Analytics v1.0<br>'
            f'{datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}'
            '</div>',
            unsafe_allow_html=True,
        )

    return selected_page


def render_footer():
    """Footer del dashboard."""
    st.markdown(
        '<div class="footer">'
        f'PricePulse Analytics — Monitoreo de precios de tecnologia en Mexico — '
        f'{datetime.now(timezone.utc).strftime("%Y")} — '
        f'Datos de Mercado Libre, AliExpress y Temu'
        f'</div>',
        unsafe_allow_html=True,
    )
