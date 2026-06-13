#!/usr/bin/env python3
"""
PricePulse Analytics — Demo Dashboard (SQLite).

Versión del dashboard que usa SQLite en lugar de PostgreSQL para
demostración sin necesidad de configurar una base de datos externa.

Los datos se cargan desde demo_pricepulse.db (generado por setup_demo.py).

Ejecución:
    # 1. Preparar datos (solo la primera vez):
    python scripts/setup_demo.py

    # 2. Iniciar dashboard:
    streamlit run src/dashboard/demo_app.py
"""

import sys
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import streamlit as st

# Asegurar path del proyecto
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config import Categories, Stores

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
DB_PATH = _PROJECT_ROOT / "demo_pricepulse.db"

st.set_page_config(
    page_title="PricePulse Analytics — Demo",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": (
            "**PricePulse Analytics** — Monitoreo de precios de tecnología "
            "en Mercado Libre, AliExpress y Temu. Demo con SQLite."
        ),
    },
)

# ---------------------------------------------------------------------------
# Colores
# ---------------------------------------------------------------------------
COLORS = {
    "primary": "#1E88E5",
    "secondary": "#00ACC1",
    "success": "#43A047",
    "warning": "#FB8C00",
    "danger": "#E53935",
    "dark": "#263238",
}

CATEGORY_COLORS = {
    "CPUs": "#1E88E5", "GPUs": "#E53935", "RAM": "#43A047",
    "SSD": "#FB8C00", "Laptops": "#8E24AA", "Monitores": "#00ACC1",
    "Placas madre": "#6D4C41",
}

STORE_COLORS = {
    "Mercado Libre": "#FFE600", "AliExpress": "#FF4747", "Temu": "#FB6F27",
}


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
def _inject_css():
    st.markdown(f"""
    <style>
    .stApp {{ font-family: 'Inter', -apple-system, sans-serif; }}
    [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, #263238 0%, #37474F 100%);
    }}
    [data-testid="stSidebar"] .stMarkdown {{ color: #ECEFF1; }}
    .kpi-card {{
        background: linear-gradient(135deg, #F5F5F5 0%, #FFFFFF 100%);
        border-radius: 12px; padding: 1.2rem 1.5rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        border-left: 4px solid {COLORS['primary']};
    }}
    .kpi-card .kpi-label {{
        font-size: 0.8rem; color: #78909C; text-transform: uppercase;
        letter-spacing: 0.5px; font-weight: 600; margin-bottom: 0.3rem;
    }}
    .kpi-card .kpi-value {{
        font-size: 1.8rem; font-weight: 700; color: #263238; line-height: 1.2;
    }}
    .section-title {{
        font-size: 1.1rem; font-weight: 700; color: #263238;
        margin-bottom: 1rem; display: flex; align-items: center; gap: 0.5rem;
    }}
    .demo-badge {{
        background: #E3F2FD; color: #1565C0; padding: 4px 12px;
        border-radius: 12px; font-size: 0.75rem; font-weight: 600;
        display: inline-block; margin-bottom: 1rem;
    }}
    [data-testid="stMetricValue"] {{ font-size: 1.6rem !important; }}
    [data-testid="stMetricLabel"] {{ font-size: 0.8rem !important; }}
    </style>
    """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Consultas SQLite
# ---------------------------------------------------------------------------
def _get_connection() -> sqlite3.Connection:
    """Obtiene conexión a SQLite."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


@st.cache_data(ttl=300)
def _load_kpis() -> dict[str, Any]:
    """Carga KPIs desde SQLite."""
    conn = _get_connection()
    try:
        c = conn.cursor()

        total_products = c.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        total_stores = c.execute("SELECT COUNT(*) FROM stores").fetchone()[0]
        total_categories = c.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        total_records = c.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]

        price_stats = c.execute(
            "SELECT AVG(price), MIN(price), MAX(price) FROM price_history"
        ).fetchone()
        avg_price = round(price_stats[0], 2) if price_stats[0] else 0
        min_price = round(price_stats[1], 2) if price_stats[1] else 0
        max_price = round(price_stats[2], 2) if price_stats[2] else 0

        # Productos con descuento (último registro con price_change_pct < 0)
        products_discount = c.execute("""
            SELECT COUNT(*) FROM (
                SELECT ph.product_id, ph.price_change_pct,
                       ROW_NUMBER() OVER (PARTITION BY ph.product_id ORDER BY ph.scraped_at DESC) as rn
                FROM price_history ph
            ) sub WHERE rn = 1 AND price_change_pct IS NOT NULL AND price_change_pct < 0
        """).fetchone()[0]

        products_price_up = c.execute("""
            SELECT COUNT(*) FROM (
                SELECT ph.product_id, ph.price_change_pct,
                       ROW_NUMBER() OVER (PARTITION BY ph.product_id ORDER BY ph.scraped_at DESC) as rn
                FROM price_history ph
            ) sub WHERE rn = 1 AND price_change_pct IS NOT NULL AND price_change_pct > 0
        """).fetchone()[0]

        last_update_row = c.execute(
            "SELECT MAX(scraped_at) FROM price_history"
        ).fetchone()
        last_update = last_update_row[0] if last_update_row[0] else None

        return {
            "total_products": total_products,
            "total_stores": total_stores,
            "total_categories": total_categories,
            "avg_price_mxn": avg_price,
            "min_price_mxn": min_price,
            "max_price_mxn": max_price,
            "products_with_discount": products_discount,
            "products_price_up": products_price_up,
            "last_update": last_update,
            "total_price_records": total_records,
        }
    finally:
        conn.close()


@st.cache_data(ttl=300)
def _load_category_summary() -> pd.DataFrame:
    """Carga resumen por categoría."""
    conn = _get_connection()
    try:
        query = """
            SELECT
                c.name as category_name,
                COUNT(DISTINCT p.id) as product_count,
                ROUND(AVG(sub.price), 2) as avg_price,
                ROUND(MIN(sub.price), 2) as min_price,
                ROUND(MAX(sub.price), 2) as max_price,
                ROUND(AVG(sub.price_change_pct), 2) as avg_discount_pct
            FROM categories c
            JOIN products p ON p.category_id = c.id
            JOIN (
                SELECT product_id, price, price_change_pct,
                       ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY scraped_at DESC) as rn
                FROM price_history
            ) sub ON sub.product_id = p.id AND sub.rn = 1
            GROUP BY c.name
            ORDER BY c.name
        """
        df = pd.read_sql_query(query, conn)
        return df
    finally:
        conn.close()


@st.cache_data(ttl=300)
def _load_top_discounts(n: int = 10) -> pd.DataFrame:
    """Carga top descuentos."""
    conn = _get_connection()
    try:
        query = f"""
            SELECT
                p.name as product_name,
                s.name as store_name,
                c.name as category_name,
                sub.price as current_price,
                (sub.price - sub.price_change) as previous_price,
                ABS(sub.price_change) as discount_amount,
                ABS(sub.price_change_pct) as discount_pct,
                sub.scraped_at
            FROM (
                SELECT product_id, price, price_change, price_change_pct, scraped_at,
                       ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY scraped_at DESC) as rn
                FROM price_history
            ) sub
            JOIN products p ON sub.product_id = p.id
            JOIN stores s ON p.store_id = s.id
            JOIN categories c ON p.category_id = c.id
            WHERE sub.rn = 1 AND sub.price_change_pct IS NOT NULL AND sub.price_change_pct < 0
            ORDER BY sub.price_change_pct ASC
            LIMIT {n}
        """
        df = pd.read_sql_query(query, conn)
        return df
    finally:
        conn.close()


@st.cache_data(ttl=300)
def _load_volatility(days: int = 30) -> pd.DataFrame:
    """Carga volatilidad por categoría.

    Nota: SQLite no tiene STDDEV, se calcula manualmente con la fórmula:
    stddev = sqrt(avg(x^2) - avg(x)^2)
    """
    conn = _get_connection()
    try:
        query = """
            SELECT
                c.name as category_name,
                ROUND(SQRT(AVG(ph.price_change_pct * ph.price_change_pct) -
                      AVG(ph.price_change_pct) * AVG(ph.price_change_pct)), 2) as volatility,
                ROUND(AVG(ph.price_change_pct), 2) as avg_change_pct,
                COUNT(ph.id) as price_records,
                COUNT(DISTINCT p.id) as products_count
            FROM categories c
            JOIN products p ON p.category_id = c.id
            JOIN price_history ph ON ph.product_id = p.id
            WHERE ph.price_change_pct IS NOT NULL
            GROUP BY c.name
            ORDER BY volatility DESC
        """
        df = pd.read_sql_query(query, conn)
        return df
    finally:
        conn.close()


@st.cache_data(ttl=300)
def _load_store_ranking() -> pd.DataFrame:
    """Carga ranking de tiendas."""
    conn = _get_connection()
    try:
        query = """
            SELECT
                s.name as store_name,
                ROUND(AVG(sub.price), 2) as avg_price,
                ROUND(MIN(sub.price), 2) as min_price,
                ROUND(MAX(sub.price), 2) as max_price,
                COUNT(DISTINCT p.id) as product_count
            FROM stores s
            JOIN products p ON p.store_id = s.id
            JOIN (
                SELECT product_id, price,
                       ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY scraped_at DESC) as rn
                FROM price_history
            ) sub ON sub.product_id = p.id AND sub.rn = 1
            GROUP BY s.name
            ORDER BY avg_price ASC
        """
        df = pd.read_sql_query(query, conn)
        df["rank"] = range(1, len(df) + 1)
        return df
    finally:
        conn.close()


@st.cache_data(ttl=300)
def _load_price_evolution(product_name: str, days: int = 30) -> pd.DataFrame:
    """Carga evolución de precio de un producto."""
    conn = _get_connection()
    try:
        query = """
            SELECT
                DATE(ph.scraped_at) as date,
                ph.price,
                ph.price_change,
                ph.price_change_pct,
                p.name as product_name,
                s.name as store_name
            FROM price_history ph
            JOIN products p ON ph.product_id = p.id
            JOIN stores s ON p.store_id = s.id
            WHERE p.name LIKE ?
            ORDER BY ph.scraped_at ASC
        """
        df = pd.read_sql_query(query, conn, params=(f"%{product_name}%",))
        return df
    finally:
        conn.close()


@st.cache_data(ttl=300)
def _load_products_by_category(category_name: str) -> pd.DataFrame:
    """Carga productos de una categoría con último precio."""
    conn = _get_connection()
    try:
        query = """
            SELECT
                p.name as product_name,
                s.name as store_name,
                sub.price as current_price,
                sub.price_change_pct,
                sub.scraped_at as last_updated
            FROM products p
            JOIN stores s ON p.store_id = s.id
            JOIN categories c ON p.category_id = c.id
            JOIN (
                SELECT product_id, price, price_change_pct, scraped_at,
                       ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY scraped_at DESC) as rn
                FROM price_history
            ) sub ON sub.product_id = p.id AND sub.rn = 1
            WHERE c.name = ?
            ORDER BY sub.price ASC
        """
        df = pd.read_sql_query(query, conn, params=(category_name,))
        return df
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
def _render_sidebar() -> str:
    with st.sidebar:
        st.markdown(
            '<div style="font-size:1.3rem;font-weight:700;color:#FFF;padding:0.5rem 0;">'
            '📊 PricePulse Analytics</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div style="font-size:0.8rem;color:#90A4AE;margin-bottom:1rem;">'
            'Demo con SQLite — Datos del mercado mexicano</div>',
            unsafe_allow_html=True,
        )
        st.markdown("---")

        st.markdown("### Navegacion")
        pages = {"Inicio": "🏠", "Tendencias": "📈", "Tiendas": "🏪", "Componentes": "🔧"}

        if "current_page" not in st.session_state:
            st.session_state.current_page = "Inicio"

        for page_name, icon in pages.items():
            if st.button(f"{icon}  {page_name}", key=f"nav_{page_name}", use_container_width=True):
                st.session_state.current_page = page_name
                st.rerun()

        st.markdown("---")

        st.markdown("### Tiendas monitoreadas")
        for store_name in Stores.ALL:
            st.markdown(f"🟢 **{store_name}**")

        st.markdown("---")

        # Botón para regenerar datos
        if st.button("🔄 Regenerar datos demo", key="regenerate", use_container_width=True):
            st.cache_data.clear()
            _setup_demo_db()
            st.success("Datos regenerados")
            st.rerun()

        st.markdown("---")
        st.markdown(
            f'<div style="text-align:center;font-size:0.7rem;color:#607D8B;">'
            f'PricePulse Analytics v1.0 — Demo<br>'
            f'BD: SQLite ({DB_PATH.name})<br>'
            f'{datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}'
            f'</div>',
            unsafe_allow_html=True,
        )

    return st.session_state.current_page


def _setup_demo_db():
    """Ejecuta setup_demo.py si la BD no existe."""
    if not DB_PATH.exists():
        from scripts.setup_demo import create_tables, seed_data
        import random
        random.seed(42)

        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        create_tables(cursor)
        seed_data(cursor)
        conn.commit()
        conn.close()


# ---------------------------------------------------------------------------
# Página: Inicio
# ---------------------------------------------------------------------------
def _render_home():
    st.markdown(
        '<h1 style="font-size:2rem;font-weight:800;color:#263238;margin-bottom:0.2rem;">'
        '📊 PricePulse Analytics</h1>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<span class="demo-badge">DEMO — Datos simulados del mercado mexicano</span>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="font-size:0.95rem;color:#78909C;margin-bottom:1.5rem;">'
        'Monitoreo en tiempo real de precios de tecnologia en Mercado Libre, AliExpress y Temu</p>',
        unsafe_allow_html=True,
    )

    kpis = _load_kpis()

    if kpis["total_products"] == 0:
        st.warning("No hay datos. Haz clic en 'Regenerar datos demo' en el sidebar.")
        return

    # ── KPIs ──────────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="🖥️ Productos monitoreados",
            value=f"{kpis['total_products']:,}",
            delta=f"{kpis['total_price_records']:,} registros de precio",
        )

    with col2:
        st.metric(
            label="💰 Precio promedio",
            value=f"${kpis['avg_price_mxn']:,.0f} MXN",
            delta=f"Min ${kpis['min_price_mxn']:,.0f} — Max ${kpis['max_price_mxn']:,.0f}",
        )

    with col3:
        st.metric(
            label="🏷️ Con descuento",
            value=f"{kpis['products_with_discount']}",
            delta=f"{kpis['products_price_up']} con aumento",
            delta_color="inverse",
        )

    with col4:
        last_update = kpis.get("last_update", "")
        if last_update:
            try:
                dt = pd.to_datetime(last_update)
                last_update_str = dt.strftime("%d/%m/%Y %H:%M")
            except Exception:
                last_update_str = str(last_update)[:16]
        else:
            last_update_str = "Sin datos"
        st.metric(
            label="🕐 Ultima actualizacion",
            value=last_update_str,
            delta=f"{kpis['total_stores']} tiendas activas",
        )

    st.markdown("---")

    # ── Gráficos ──────────────────────────────────────────────────────
    col_chart, col_vol = st.columns([3, 2])

    with col_chart:
        st.markdown('<div class="section-title">📊 Precio promedio por categoria</div>', unsafe_allow_html=True)
        cat_df = _load_category_summary()
        if not cat_df.empty:
            colors = [CATEGORY_COLORS.get(c, COLORS["primary"]) for c in cat_df["category_name"]]
            fig = go.Figure(go.Bar(
                x=cat_df["category_name"], y=cat_df["avg_price"],
                marker_color=colors,
                text=[f"${p:,.0f}" for p in cat_df["avg_price"]],
                textposition="auto", textfont=dict(size=11, color="white"),
                hovertemplate="<b>%{x}</b><br>Precio promedio: $%{y:,.0f} MXN<extra></extra>",
            ))
            fig.update_layout(
                height=380, margin=dict(l=20, r=20, t=10, b=40),
                yaxis_title="Precio (MXN)", yaxis_tickformat="$,.0f",
                showlegend=False, plot_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(gridcolor="rgba(0,0,0,0.05)", tickangle=-15),
                yaxis=dict(gridcolor="rgba(0,0,0,0.05)"), bargap=0.3,
            )
            st.plotly_chart(fig, use_container_width=True)

            # Sub-métricas
            cols = st.columns(min(len(cat_df), 4))
            for idx, (_, row) in enumerate(cat_df.iterrows()):
                with cols[idx % len(cols)]:
                    cat_name = row["category_name"]
                    cat_color = CATEGORY_COLORS.get(cat_name, COLORS["primary"])
                    discount = row.get("avg_discount_pct", 0)
                    discount_str = f"{discount:+.1f}%" if pd.notna(discount) else "N/A"
                    st.markdown(
                        f'<div style="border-left:3px solid {cat_color};padding-left:8px;margin:0.3rem 0;">'
                        f'<span style="font-size:0.75rem;color:#78909C;">{cat_name}</span><br>'
                        f'<span style="font-size:1.1rem;font-weight:700;">${row["avg_price"]:,.0f}</span> '
                        f'<span style="font-size:0.75rem;">({int(row["product_count"])} productos)</span><br>'
                        f'<span style="font-size:0.75rem;">Variacion: {discount_str}</span></div>',
                        unsafe_allow_html=True,
                    )

    with col_vol:
        st.markdown('<div class="section-title">📉 Volatilidad por categoria</div>', unsafe_allow_html=True)
        vol_df = _load_volatility()
        if not vol_df.empty:
            colors = [CATEGORY_COLORS.get(c, COLORS["primary"]) for c in vol_df["category_name"]]
            fig = go.Figure(go.Bar(
                x=vol_df["category_name"], y=vol_df["volatility"],
                marker_color=colors,
                text=[f"{v:.1f}%" for v in vol_df["volatility"].fillna(0)],
                textposition="auto", textfont=dict(size=10, color="white"),
                hovertemplate="<b>%{x}</b><br>Volatilidad: %{y:.2f}%<extra></extra>",
            ))
            fig.update_layout(
                height=380, margin=dict(l=20, r=20, t=10, b=40),
                yaxis_title="Volatilidad (%)", showlegend=False,
                plot_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(gridcolor="rgba(0,0,0,0.05)", tickangle=-15),
                yaxis=dict(gridcolor="rgba(0,0,0,0.05)"), bargap=0.3,
            )
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # ── Top Descuentos ────────────────────────────────────────────────
    st.markdown('<div class="section-title">🔥 Top 10 productos con mayor descuento</div>', unsafe_allow_html=True)
    disc_df = _load_top_discounts(n=10)

    if not disc_df.empty:
        display_df = disc_df.copy()
        display_df["Precio actual"] = display_df["current_price"].apply(lambda x: f"${x:,.2f}")
        display_df["Precio anterior"] = display_df["previous_price"].apply(lambda x: f"${x:,.2f}")
        display_df["Descuento"] = display_df["discount_amount"].apply(lambda x: f"${x:,.2f}")
        display_df["Variacion"] = display_df["discount_pct"].apply(lambda x: f"-{x:.1f}%")

        if "scraped_at" in display_df.columns:
            display_df["Fecha"] = pd.to_datetime(display_df["scraped_at"]).dt.strftime("%d/%m/%Y")
        else:
            display_df["Fecha"] = "—"

        display_df = display_df[[
            "product_name", "store_name", "category_name",
            "Precio actual", "Precio anterior", "Descuento", "Variacion", "Fecha",
        ]].rename(columns={
            "product_name": "Producto", "store_name": "Tienda",
            "category_name": "Categoria",
        })
        display_df.index = range(1, len(display_df) + 1)
        display_df.index.name = "#"

        st.dataframe(display_df, use_container_width=True, height=min(400, 35 + 35 * len(display_df)))

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Descuento maximo", f"-{disc_df['discount_pct'].max():.1f}%")
        with col2:
            st.metric("Descuento promedio", f"-{disc_df['discount_pct'].mean():.1f}%")
        with col3:
            st.metric("Ahorro total potencial", f"${disc_df['discount_amount'].sum():,.0f} MXN")
    else:
        st.info("No se encontraron productos con descuento en el periodo actual.")


# ---------------------------------------------------------------------------
# Página: Tendencias
# ---------------------------------------------------------------------------
def _render_trends():
    st.markdown(
        '<h1 style="font-size:1.8rem;font-weight:800;color:#263238;">📈 Tendencias de Precios</h1>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="font-size:0.9rem;color:#78909C;margin-bottom:1.5rem;">'
        'Analiza la evolucion historica de precios por producto</p>',
        unsafe_allow_html=True,
    )

    # Selector de producto
    conn = _get_connection()
    try:
        products = pd.read_sql_query(
            "SELECT DISTINCT name FROM products ORDER BY name", conn
        )
    finally:
        conn.close()

    if products.empty:
        st.warning("No hay productos disponibles.")
        return

    selected = st.selectbox(
        "Selecciona un producto para ver su evolucion:",
        options=products["name"].tolist(),
        index=0,
    )

    if selected:
        evo_df = _load_price_evolution(selected)
        if not evo_df.empty:
            # Gráfico de evolución por tienda
            fig = go.Figure()

            for store_name in evo_df["store_name"].unique():
                store_data = evo_df[evo_df["store_name"] == store_name]
                store_color = STORE_COLORS.get(store_name, COLORS["primary"])
                fig.add_trace(go.Scatter(
                    x=store_data["date"], y=store_data["price"],
                    mode="lines+markers", name=store_name,
                    line=dict(color=store_color, width=2),
                    marker=dict(size=8),
                    hovertemplate=f"<b>{store_name}</b><br>Fecha: %{{x}}<br>Precio: $%{{y:,.0f}} MXN<extra></extra>",
                ))

            fig.update_layout(
                height=500,
                title=f"Evolucion de precio: {selected[:60]}",
                xaxis_title="Fecha", yaxis_title="Precio (MXN)",
                yaxis_tickformat="$,.0f",
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                plot_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(gridcolor="rgba(0,0,0,0.05)"),
                yaxis=dict(gridcolor="rgba(0,0,0,0.05)"),
            )

            st.plotly_chart(fig, use_container_width=True)

            # Tabla de datos
            display_df = evo_df.copy()
            display_df["Precio"] = display_df["price"].apply(lambda x: f"${x:,.2f}")
            display_df["Variacion"] = display_df["price_change_pct"].apply(
                lambda x: f"{x:+.1f}%" if pd.notna(x) else "—"
            )
            display_df = display_df[["date", "store_name", "Precio", "Variacion"]].rename(columns={
                "date": "Fecha", "store_name": "Tienda",
            })
            st.dataframe(display_df, use_container_width=True, hide_index=True)
        else:
            st.info("No hay datos de evolucion para este producto.")


# ---------------------------------------------------------------------------
# Página: Tiendas
# ---------------------------------------------------------------------------
def _render_stores():
    st.markdown(
        '<h1 style="font-size:1.8rem;font-weight:800;color:#263238;">🏪 Comparacion de Tiendas</h1>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="font-size:0.9rem;color:#78909C;margin-bottom:1.5rem;">'
        'Compara precios entre Mercado Libre, AliExpress y Temu</p>',
        unsafe_allow_html=True,
    )

    ranking_df = _load_store_ranking()
    if ranking_df.empty:
        st.warning("No hay datos de tiendas.")
        return

    # Gráfico comparativo
    fig = go.Figure()
    colors = [STORE_COLORS.get(s, COLORS["primary"]) for s in ranking_df["store_name"]]

    fig.add_trace(go.Bar(
        x=ranking_df["store_name"], y=ranking_df["avg_price"],
        marker_color=colors,
        text=[f"${p:,.0f}" for p in ranking_df["avg_price"]],
        textposition="auto", textfont=dict(size=13, color="#263238"),
        hovertemplate="<b>%{x}</b><br>Precio promedio: $%{y:,.0f} MXN<br>Productos: %{customdata[0]}<extra></extra>",
        customdata=[[int(r)] for r in ranking_df["product_count"]],
    ))

    fig.update_layout(
        height=400, margin=dict(l=20, r=20, t=20, b=40),
        yaxis_title="Precio promedio (MXN)", yaxis_tickformat="$,.0f",
        showlegend=False, plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(gridcolor="rgba(0,0,0,0.05)"),
        yaxis=dict(gridcolor="rgba(0,0,0,0.05)"), bargap=0.4,
    )

    st.plotly_chart(fig, use_container_width=True)

    # KPIs por tienda
    cols = st.columns(len(ranking_df))
    for idx, (_, row) in enumerate(ranking_df.iterrows()):
        with cols[idx]:
            rank_emoji = "🥇" if row["rank"] == 1 else "🥈" if row["rank"] == 2 else "🥉"
            st.metric(
                label=f"{rank_emoji} {row['store_name']}",
                value=f"${row['avg_price']:,.0f} MXN",
                delta=f"Ranking #{int(row['rank'])} — {int(row['product_count'])} productos",
            )

    st.markdown("---")

    # Tabla detallada
    st.markdown("### Detalle por tienda")
    display_df = ranking_df.rename(columns={
        "rank": "#", "store_name": "Tienda", "avg_price": "Precio Promedio",
        "min_price": "Minimo", "max_price": "Maximo", "product_count": "Productos",
    })
    st.dataframe(display_df, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Página: Componentes
# ---------------------------------------------------------------------------
def _render_components():
    st.markdown(
        '<h1 style="font-size:1.8rem;font-weight:800;color:#263238;">🔧 Componentes por Categoria</h1>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="font-size:0.9rem;color:#78909C;margin-bottom:1.5rem;">'
        'Detalle de precios y variaciones por tipo de componente</p>',
        unsafe_allow_html=True,
    )

    selected_cat = st.selectbox(
        "Selecciona una categoria:",
        options=Categories.ALL,
        index=0,
    )

    if selected_cat:
        products_df = _load_products_by_category(selected_cat)

        if not products_df.empty:
            cat_color = CATEGORY_COLORS.get(selected_cat, COLORS["primary"])

            # Gráfico de barras por tienda
            fig = go.Figure()
            for store_name in products_df["store_name"].unique():
                store_data = products_df[products_df["store_name"] == store_name]
                store_color = STORE_COLORS.get(store_name, COLORS["primary"])
                fig.add_trace(go.Bar(
                    x=store_data["product_name"].str[:40],
                    y=store_data["current_price"],
                    name=store_name,
                    marker_color=store_color,
                    hovertemplate=f"<b>{store_name}</b><br>%{{x}}<br>Precio: $%{{y:,.0f}}<extra></extra>",
                ))

            fig.update_layout(
                height=450,
                title=f"Precios en {selected_cat}",
                yaxis_title="Precio (MXN)", yaxis_tickformat="$,.0f",
                barmode="group",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                plot_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(gridcolor="rgba(0,0,0,0.05)", tickangle=-30),
                yaxis=dict(gridcolor="rgba(0,0,0,0.05)"),
            )

            st.plotly_chart(fig, use_container_width=True)

            # Tabla de productos
            display_df = products_df.copy()
            display_df["Precio"] = display_df["current_price"].apply(lambda x: f"${x:,.2f}")
            display_df["Variacion"] = display_df["price_change_pct"].apply(
                lambda x: f"{x:+.1f}%" if pd.notna(x) else "—"
            )
            display_df = display_df[["product_name", "store_name", "Precio", "Variacion"]].rename(columns={
                "product_name": "Producto", "store_name": "Tienda",
            })
            st.dataframe(display_df, use_container_width=True, hide_index=True)
        else:
            st.info(f"No hay productos en la categoria {selected_cat}.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    _inject_css()

    # Crear BD demo si no existe
    _setup_demo_db()

    current_page = _render_sidebar()

    pages = {
        "Inicio": _render_home,
        "Tendencias": _render_trends,
        "Tiendas": _render_stores,
        "Componentes": _render_components,
    }

    pages.get(current_page, _render_home)()

    # Footer
    st.markdown(
        '<div style="text-align:center;color:#90A4AE;font-size:0.75rem;padding:1rem 0;'
        'border-top:1px solid #E0E0E0;margin-top:2rem;">'
        f'PricePulse Analytics — Demo con SQLite — {datetime.now(timezone.utc).strftime("%Y")} — '
        f'Mercado Libre, AliExpress, Temu</div>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
