"""Pagina de Inicio: KPIs, precio por categoria, top descuentos."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dashboard.common.styles import COLORS, CATEGORY_COLORS
from src.dashboard.common.loaders import (
    load_kpi_summary,
    load_category_summary,
    load_top_discounts,
    load_category_volatility,
)


def render():
    """Renderiza la pagina principal con KPIs, graficos y tabla de descuentos."""
    st.markdown(
        '<h1 style="font-size:2rem;font-weight:800;color:#263238;margin-bottom:0.2rem;">'
        '📊 PricePulse Analytics</h1>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="font-size:0.95rem;color:#78909C;margin-bottom:1.5rem;">'
        'Monitoreo en tiempo real de precios de tecnologia en el mercado mexicano</p>',
        unsafe_allow_html=True,
    )

    kpis_df = load_kpi_summary()
    category_df = load_category_summary()
    discounts_df = load_top_discounts(n=10)

    has_data = not kpis_df.empty and kpis_df.get("total_products", pd.Series([0])).iloc[0] > 0

    if not has_data:
        st.warning("⚠️ No hay datos en la base de datos. Ejecuta el pipeline o el script de seed.")
        st.info(
            "💡 **Opciones:**\n"
            "1. Haz clic en **'Ejecutar Pipeline'** en el sidebar\n"
            "2. Ejecuta: `python scripts/seed_data.py`"
        )
        return

    # KPIs
    total_products = int(kpis_df["total_products"].iloc[0])
    avg_price = float(kpis_df["avg_price_mxn"].iloc[0])
    products_discount = int(kpis_df["products_with_discount"].iloc[0])
    last_update = kpis_df["last_update"].iloc[0]
    total_records = int(kpis_df["total_price_records"].iloc[0])
    products_price_up = int(kpis_df.get("products_price_up", pd.Series([0])).iloc[0])

    if pd.notna(last_update):
        try:
            last_update_dt = pd.Timestamp(last_update) if not isinstance(last_update, str) else pd.to_datetime(last_update)
            last_update_str = last_update_dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            last_update_str = str(last_update)
    else:
        last_update_str = "Sin datos"

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("🖥️ Productos monitoreados", f"{total_products:,}", delta=f"{total_records:,} registros de precio")
    with col2:
        st.metric(
            "💰 Precio promedio", f"${avg_price:,.0f} MXN",
            delta=f"Min ${float(kpis_df['min_price_mxn'].iloc[0]):,.0f} — Max ${float(kpis_df['max_price_mxn'].iloc[0]):,.0f}",
        )
    with col3:
        st.metric("🏷️ Con descuento", f"{products_discount}", delta=f"{products_price_up} con aumento", delta_color="inverse")
    with col4:
        st.metric("🕐 Ultima actualizacion", last_update_str, delta=f"{int(kpis_df['total_stores'].iloc[0])} tiendas activas")

    st.markdown("---")

    # Graficos: precio por categoria + volatilidad
    col_chart, col_volatility = st.columns([3, 2])

    with col_chart:
        st.markdown('<div class="section-title">📊 Precio promedio por categoria</div>', unsafe_allow_html=True)
        _render_category_price_chart(category_df)

    with col_volatility:
        st.markdown('<div class="section-title">📉 Volatilidad por categoria</div>', unsafe_allow_html=True)
        _render_volatility_chart()

    st.markdown("---")

    # Top descuentos
    st.markdown('<div class="section-title">🔥 Top 10 productos con mayor descuento</div>', unsafe_allow_html=True)
    _render_discounts_table(discounts_df)


def _render_category_price_chart(category_df: pd.DataFrame):
    if category_df.empty:
        st.info("No hay datos de categorias disponibles.")
        return

    colors = [CATEGORY_COLORS.get(cat, COLORS["primary"]) for cat in category_df["category_name"]]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=category_df["category_name"],
        y=category_df["avg_price"],
        name="Precio promedio",
        marker_color=colors,
        marker_line_color="rgba(0,0,0,0.1)",
        marker_line_width=1,
        text=[f"${p:,.0f}" for p in category_df["avg_price"]],
        textposition="auto",
        textfont=dict(size=11, color="white"),
        hovertemplate="<b>%{x}</b><br>Precio promedio: $%{y:,.0f} MXN<br><extra></extra>",
    ))

    fig.add_trace(go.Bar(
        x=category_df["category_name"],
        y=category_df["max_price"],
        name="Precio maximo",
        marker_color="rgba(0,0,0,0.05)",
        hovertemplate="<b>%{x}</b><br>Precio maximo: $%{y:,.0f} MXN<br><extra></extra>",
        visible="legendonly",
    ))

    fig.update_layout(
        height=380, margin=dict(l=20, r=20, t=10, b=40),
        xaxis_title=None, yaxis_title="Precio (MXN)", yaxis_tickformat="$,.0f",
        showlegend=False, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(gridcolor="rgba(0,0,0,0.05)", tickangle=-15),
        yaxis=dict(gridcolor="rgba(0,0,0,0.05)"),
        bargap=0.3,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Sub-metricas por categoria
    if not category_df.empty:
        cols = st.columns(min(len(category_df), 4))
        for idx, (_, row) in enumerate(category_df.iterrows()):
            with cols[idx % len(cols)]:
                cat_name = row["category_name"]
                cat_color = CATEGORY_COLORS.get(cat_name, COLORS["primary"])
                avg_discount = row.get("avg_discount_pct", 0)
                discount_str = f"{avg_discount:+.1f}%" if pd.notna(avg_discount) else "N/A"
                st.markdown(
                    f'<div style="border-left:3px solid {cat_color};padding-left:8px;margin:0.3rem 0;">'
                    f'<span style="font-size:0.75rem;color:#78909C;">{cat_name}</span><br>'
                    f'<span style="font-size:1.1rem;font-weight:700;">${row["avg_price"]:,.0f}</span> '
                    f'<span style="font-size:0.75rem;">({int(row["product_count"])} productos)</span><br>'
                    f'<span style="font-size:0.75rem;">Variacion: {discount_str}</span></div>',
                    unsafe_allow_html=True,
                )


def _render_volatility_chart():
    volatility_df = load_category_volatility(days=30)
    if volatility_df.empty:
        st.info("No hay datos de volatilidad disponibles.")
        return

    colors = [CATEGORY_COLORS.get(cat, COLORS["primary"]) for cat in volatility_df["category_name"]]

    fig = go.Figure(go.Bar(
        x=volatility_df["category_name"],
        y=volatility_df["volatility"],
        marker_color=colors,
        marker_line_color="rgba(0,0,0,0.1)",
        marker_line_width=1,
        text=[f"{v:.1f}%" for v in volatility_df["volatility"]],
        textposition="auto",
        textfont=dict(size=10, color="white"),
        hovertemplate=(
            "<b>%{x}</b><br>Volatilidad: %{y:.2f}%<br>"
            "Variacion promedio: %{customdata[0]:.2f}%<br>Productos: %{customdata[1]}<br><extra></extra>"
        ),
        customdata=list(zip(volatility_df["avg_change_pct"].fillna(0), volatility_df["products_count"])),
    ))

    fig.update_layout(
        height=380, margin=dict(l=20, r=20, t=10, b=40),
        xaxis_title=None, yaxis_title="Volatilidad (%)", yaxis_tickformat=".1f%",
        showlegend=False, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(gridcolor="rgba(0,0,0,0.05)", tickangle=-15),
        yaxis=dict(gridcolor="rgba(0,0,0,0.05)"),
        bargap=0.3,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_discounts_table(discounts_df: pd.DataFrame):
    if discounts_df.empty:
        st.info("No se encontraron productos con descuento. Los precios pueden estar estables.")
        return

    display_df = discounts_df.copy()
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
        "product_name": "Producto",
        "store_name": "Tienda",
        "category_name": "Categoria",
    })
    display_df.index = range(1, len(display_df) + 1)
    display_df.index.name = "#"

    st.dataframe(
        display_df, use_container_width=True,
        height=min(400, 35 + 35 * len(display_df)),
        column_config={
            "Producto": st.column_config.TextColumn(width="large"),
            "Tienda": st.column_config.TextColumn(width="small"),
            "Categoria": st.column_config.TextColumn(width="small"),
            "Precio actual": st.column_config.TextColumn(width="small"),
            "Precio anterior": st.column_config.TextColumn(width="small"),
            "Descuento": st.column_config.TextColumn(width="small"),
            "Variacion": st.column_config.TextColumn(width="small", help="Variacion porcentual vs precio anterior"),
            "Fecha": st.column_config.TextColumn(width="small"),
        },
    )

    if not discounts_df.empty:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Descuento maximo", f"-{discounts_df['discount_pct'].max():.1f}%")
        with col2:
            st.metric("Descuento promedio", f"-{discounts_df['discount_pct'].mean():.1f}%")
        with col3:
            st.metric("Ahorro total potencial", f"${discounts_df['discount_amount'].sum():,.0f} MXN")
