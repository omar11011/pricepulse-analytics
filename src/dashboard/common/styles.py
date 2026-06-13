"""Colores, constantes y CSS del dashboard."""

import streamlit as st

# Colores base del tema
COLORS = {
    "primary": "#1E88E5",
    "secondary": "#00ACC1",
    "success": "#43A047",
    "warning": "#FB8C00",
    "danger": "#E53935",
    "dark": "#263238",
    "light": "#ECEFF1",
    "background": "#FFFFFF",
    "card_bg": "#F5F5F5",
}

# Un color por categoria para que los graficos sean consistentes
CATEGORY_COLORS = {
    "CPUs": "#1E88E5",
    "GPUs": "#E53935",
    "RAM": "#43A047",
    "SSD": "#FB8C00",
    "Laptops": "#8E24AA",
    "Monitores": "#00ACC1",
    "Placas madre": "#6D4C41",
}

# Colores oficiales de cada tienda
STORE_COLORS = {
    "Mercado Libre": "#FFE600",
    "AliExpress": "#FF4747",
    "Temu": "#FB6F27",
}

# Iconos para el sidebar
STORE_STATUS_ICONS = {
    "Mercado Libre": "🟡",
    "AliExpress": "🔴",
    "Temu": "🟠",
}


def inject_custom_css():
    """Inyecta el CSS custom para que el dashboard no se vea default."""
    st.markdown(f"""
    <style>
    /* General */
    .stApp {{
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }}

    /* KPI cards */
    .kpi-card {{
        background: linear-gradient(135deg, {COLORS['card_bg']} 0%, #FFFFFF 100%);
        border-radius: 12px;
        padding: 1.2rem 1.5rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        border-left: 4px solid {COLORS['primary']};
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }}
    .kpi-card:hover {{
        transform: translateY(-2px);
        box-shadow: 0 4px 16px rgba(0,0,0,0.12);
    }}
    .kpi-card .kpi-label {{
        font-size: 0.8rem;
        color: #78909C;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        font-weight: 600;
        margin-bottom: 0.3rem;
    }}
    .kpi-card .kpi-value {{
        font-size: 1.8rem;
        font-weight: 700;
        color: {COLORS['dark']};
        line-height: 1.2;
    }}
    .kpi-card .kpi-delta {{
        font-size: 0.85rem;
        margin-top: 0.2rem;
    }}
    .kpi-delta.positive {{ color: {COLORS['success']}; }}
    .kpi-delta.negative {{ color: {COLORS['danger']}; }}

    /* Sidebar oscuro */
    [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, {COLORS['dark']} 0%, #37474F 100%);
    }}
    [data-testid="stSidebar"] .stMarkdown {{
        color: #ECEFF1;
    }}
    .sidebar-title {{
        font-size: 1.3rem;
        font-weight: 700;
        color: #FFFFFF;
        padding: 0.5rem 0;
        margin-bottom: 0.5rem;
    }}
    .sidebar-subtitle {{
        font-size: 0.8rem;
        color: #90A4AE;
        margin-bottom: 1rem;
    }}

    /* Nav items */
    .nav-item {{
        padding: 0.6rem 1rem;
        margin: 0.2rem 0;
        border-radius: 8px;
        cursor: pointer;
        transition: background 0.2s ease;
        font-size: 0.95rem;
    }}
    .nav-item:hover {{ background: rgba(255,255,255,0.1); }}
    .nav-item.active {{
        background: {COLORS['primary']};
        color: #FFFFFF;
        font-weight: 600;
    }}

    /* Charts y secciones */
    .chart-section {{
        background: #FFFFFF;
        border-radius: 12px;
        padding: 1.5rem;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06);
        margin-bottom: 1.5rem;
    }}
    .section-title {{
        font-size: 1.1rem;
        font-weight: 700;
        color: {COLORS['dark']};
        margin-bottom: 1rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }}

    /* Badges de descuento/aumento */
    .discount-badge {{
        background: {COLORS['success']};
        color: white;
        padding: 2px 8px;
        border-radius: 10px;
        font-size: 0.8rem;
        font-weight: 600;
    }}
    .price-up-badge {{
        background: {COLORS['danger']};
        color: white;
        padding: 2px 8px;
        border-radius: 10px;
        font-size: 0.8rem;
        font-weight: 600;
    }}

    /* Footer */
    .footer {{
        text-align: center;
        color: #90A4AE;
        font-size: 0.75rem;
        padding: 1rem 0;
        border-top: 1px solid #E0E0E0;
        margin-top: 2rem;
    }}

    /* Pipeline status badges */
    .pipeline-success {{
        background: #E8F5E9;
        border-left: 4px solid {COLORS['success']};
        padding: 1rem;
        border-radius: 8px;
    }}
    .pipeline-partial {{
        background: #FFF3E0;
        border-left: 4px solid {COLORS['warning']};
        padding: 1rem;
        border-radius: 8px;
    }}
    .pipeline-failure {{
        background: #FFEBEE;
        border-left: 4px solid {COLORS['danger']};
        padding: 1rem;
        border-radius: 8px;
    }}

    /* Boton de pipeline con gradiente */
    .stButton > button {{
        width: 100%;
        background: linear-gradient(135deg, {COLORS['primary']} 0%, {COLORS['secondary']} 100%);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 0.6rem 1.2rem;
        font-weight: 600;
        transition: all 0.2s ease;
    }}
    .stButton > button:hover {{
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(30,136,229,0.4);
    }}

    /* Metricas */
    [data-testid="stMetricValue"] {{ font-size: 1.6rem !important; }}
    [data-testid="stMetricLabel"] {{ font-size: 0.8rem !important; }}
    </style>
    """, unsafe_allow_html=True)
