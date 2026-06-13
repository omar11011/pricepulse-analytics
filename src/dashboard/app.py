"""PricePulse Analytics — Dashboard Streamlit.

Uso:
    streamlit run src/dashboard/app.py
    streamlit run src/dashboard/app.py --server.port 8501
"""

import sys
from pathlib import Path

import streamlit as st

# Path setup para imports
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.dashboard.common.styles import inject_custom_css
from src.dashboard.common.utils import ensure_database_populated, render_sidebar, render_footer
from src.dashboard.pages.home import render as render_home
from src.dashboard.pages.trends import render as render_trends
from src.dashboard.pages.stores import render as render_stores
from src.dashboard.pages.components import render as render_components

# Config de pagina — debe ser el primer comando de Streamlit
st.set_page_config(
    page_title="PricePulse Analytics",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": "https://github.com/omar11011/pricepulse-analytics",
        "Report a Bug": "https://github.com/omar11011/pricepulse-analytics/issues",
        "About": (
            "**PricePulse Analytics** — Monitoreo de precios de tecnologia "
            "en Mercado Libre, AliExpress y Temu."
        ),
    },
)


def main():
    # Auto-seed si la BD esta vacia (importante para Streamlit Cloud)
    ensure_database_populated()

    # CSS custom
    inject_custom_css()

    # Sidebar + navegacion
    current_page = render_sidebar()

    # Renderizar la pagina que corresponda
    pages = {
        "Inicio": render_home,
        "Tendencias": render_trends,
        "Tiendas": render_stores,
        "Componentes": render_components,
    }
    renderer = pages.get(current_page, render_home)
    renderer()

    # Footer
    render_footer()


if __name__ == "__main__":
    main()
