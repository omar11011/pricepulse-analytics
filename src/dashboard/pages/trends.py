"""Pagina de Tendencias: evolucion de precios, mejor momento, variaciones."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dashboard.common.styles import COLORS, CATEGORY_COLORS, STORE_COLORS
from src.dashboard.common.loaders import (
    load_products_list,
    load_category_summary,
    load_category_volatility,
    load_price_changes,
    load_category_price_stats,
)
from src.dashboard.common.utils import get_analytics_service


def render():
    """Renderiza la pagina de tendencias con evolucion de precios."""
    st.markdown(
        '<h1 style="font-size:1.8rem;font-weight:800;color:#263238;">📈 Tendencias de Precios</h1>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="font-size:0.9rem;color:#78909C;margin-bottom:1.5rem;">'
        'Analiza la evolucion historica de precios por producto y categoria</p>',
        unsafe_allow_html=True,
    )

    products_df = load_products_list()
    category_df = load_category_summary()

    if products_df.empty:
        st.warning("⚠️ No hay datos. Ejecuta el pipeline o el script de seed.")
        return

    # Filtros
    col_cat, col_prod, col_days = st.columns([2, 4, 1])

    with col_cat:
        categories = ["Todas"] + sorted(products_df["category_name"].unique().tolist())
        selected_category = st.selectbox("📂 Categoria", options=categories, index=0, key="trends_category")

    if selected_category == "Todas":
        filtered_products = products_df
        category_id_filter = None
    else:
        filtered_products = products_df[products_df["category_name"] == selected_category]
        category_id_filter = int(filtered_products["category_id"].iloc[0])

    with col_prod:
        product_options = filtered_products["name"].unique().tolist()
        if not product_options:
            st.info("No hay productos en esta categoria.")
            return
        selected_product_name = st.selectbox("🔍 Producto", options=product_options, index=0, key="trends_product")
        product_row = filtered_products[filtered_products["name"] == selected_product_name].iloc[0]
        selected_product_id = int(product_row["id"])

    with col_days:
        days_options = {"7 dias": 7, "15 dias": 15, "30 dias": 30, "90 dias": 90}
        selected_days_label = st.selectbox("📅 Periodo", options=list(days_options.keys()), index=2, key="trends_days")
        selected_days = days_options[selected_days_label]

    st.markdown("---")

    # 1. Evolucion del producto
    _render_product_evolution_chart(selected_product_id, selected_product_name, selected_days)

    st.markdown("---")

    # 2. Variacion por categoria + mejor dia
    col_cat_evo, col_best_day = st.columns([3, 2])
    with col_cat_evo:
        _render_category_temporal_chart(category_df, selected_days)
    with col_best_day:
        _render_best_time_chart(category_id_filter, selected_days)

    st.markdown("---")

    # 3. Histograma + Boxplot
    col_hist, col_box = st.columns(2)
    with col_hist:
        _render_variation_histogram(selected_days, category_id_filter)
    with col_box:
        _render_category_boxplot(selected_days)


def _render_product_evolution_chart(product_id: int, product_name: str, days: int):
    st.markdown(
        '<div class="section-title">📉 Evolucion de precio: '
        f'{product_name[:50]}{"..." if len(product_name) > 50 else ""}</div>',
        unsafe_allow_html=True,
    )

    service = get_analytics_service()
    all_products = load_products_list()
    same_products = all_products[all_products["name"] == product_name]

    fig = go.Figure()
    has_data = False

    for _, prod_row in same_products.iterrows():
        pid = int(prod_row["id"])
        store = prod_row["store_name"]
        evo_df = service.get_price_evolution(product_id=pid, days=days)
        if evo_df.empty:
            continue
        has_data = True
        store_color = STORE_COLORS.get(store, COLORS["primary"])
        fig.add_trace(go.Scatter(
            x=evo_df["date"], y=evo_df["price"],
            mode="lines+markers", name=store,
            line=dict(color=store_color, width=2.5),
            marker=dict(size=6, symbol="circle"),
            hovertemplate="<b>%{fullData.name}</b><br>Fecha: %{x}<br>Precio: $%{y:,.2f} MXN<br><extra></extra>",
        ))

    if not has_data:
        st.info(f"No hay datos de evolucion para **{product_name[:40]}** en los ultimos {days} dias.")
        return

    # Anotaciones de min/max
    all_prices = []
    for _, prod_row in same_products.iterrows():
        evo_df = service.get_price_evolution(product_id=int(prod_row["id"]), days=days)
        if not evo_df.empty:
            all_prices.extend(evo_df["price"].tolist())

    if all_prices:
        min_price, max_price = min(all_prices), max(all_prices)
        fig.add_hline(y=min_price, line_dash="dot", line_color=COLORS["success"], opacity=0.6,
                      annotation_text=f"Min: ${min_price:,.0f}", annotation_position="bottom right", annotation_font_size=10)
        fig.add_hline(y=max_price, line_dash="dot", line_color=COLORS["danger"], opacity=0.6,
                      annotation_text=f"Max: ${max_price:,.0f}", annotation_position="top right", annotation_font_size=10)

    fig.update_layout(
        height=420, margin=dict(l=20, r=20, t=10, b=40),
        xaxis_title="Fecha", yaxis_title="Precio (MXN)", yaxis_tickformat="$,.0f",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(gridcolor="rgba(0,0,0,0.05)"), yaxis=dict(gridcolor="rgba(0,0,0,0.05)"),
    )
    st.plotly_chart(fig, use_container_width=True)

    if all_prices:
        avg_price = sum(all_prices) / len(all_prices)
        price_range = max_price - min_price
        col1, col2, col3, col4 = st.columns(4)
        with col1: st.metric("Precio minimo", f"${min_price:,.0f}")
        with col2: st.metric("Precio maximo", f"${max_price:,.0f}")
        with col3: st.metric("Rango", f"${price_range:,.0f}")
        with col4: st.metric("Precio promedio", f"${avg_price:,.0f}")


def _render_category_temporal_chart(category_df: pd.DataFrame, days: int):
    st.markdown('<div class="section-title">📊 Variacion promedio por categoria</div>', unsafe_allow_html=True)

    if category_df.empty:
        st.info("No hay datos de categorias.")
        return

    volatility_df = load_category_volatility(days=days)
    if volatility_df.empty:
        st.info("No hay datos de variacion para este periodo.")
        return

    colors = [CATEGORY_COLORS.get(cat, COLORS["primary"]) for cat in volatility_df["category_name"]]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=volatility_df["category_name"],
        x=volatility_df["avg_change_pct"],
        orientation="h",
        marker_color=colors,
        marker_line_color="rgba(0,0,0,0.1)",
        marker_line_width=1,
        text=[f"{v:+.2f}%" if pd.notna(v) else "N/A" for v in volatility_df["avg_change_pct"]],
        textposition="auto",
        textfont=dict(size=11),
        hovertemplate=(
            "<b>%{y}</b><br>Variacion promedio: %{x:+.2f}%<br>"
            "Volatilidad: %{customdata[0]:.2f}%<br>Productos: %{customdata[1]}<br><extra></extra>"
        ),
        customdata=list(zip(volatility_df["volatility"].fillna(0), volatility_df["products_count"])),
    ))
    fig.add_vline(x=0, line_dash="dash", line_color="rgba(0,0,0,0.3)", line_width=1)

    fig.update_layout(
        height=380, margin=dict(l=20, r=20, t=10, b=40),
        xaxis_title="Variacion promedio (%)", yaxis_title=None,
        showlegend=False, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(gridcolor="rgba(0,0,0,0.05)"), yaxis=dict(gridcolor="rgba(0,0,0,0.02)"),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_best_time_chart(category_id: int | None, days: int):
    st.markdown('<div class="section-title">🗓️ Mejor dia para comprar</div>', unsafe_allow_html=True)

    service = get_analytics_service()
    btb_df = service.get_best_time_to_buy(category_id=category_id, days=days)

    if btb_df.empty:
        st.info("No hay datos suficientes para este analisis.")
        return

    colors = [COLORS["success"] if is_best else COLORS["primary"] for is_best in btb_df["is_best"]]

    fig = go.Figure(go.Bar(
        x=btb_df["day_of_week"], y=btb_df["avg_price"],
        marker_color=colors,
        marker_line_color="rgba(0,0,0,0.1)",
        marker_line_width=1,
        text=[f"${p:,.0f}" for p in btb_df["avg_price"]],
        textposition="auto",
        textfont=dict(size=10, color="white"),
        hovertemplate=(
            "<b>%{x}</b><br>Precio promedio: $%{y:,.0f} MXN<br>"
            "Min: $%{customdata[0]:,.0f} | Max: $%{customdata[1]:,.0f}<br>Registros: %{customdata[2]}<br><extra></extra>"
        ),
        customdata=list(zip(btb_df["min_price"], btb_df["max_price"], btb_df["price_records"])),
    ))

    best_row = btb_df[btb_df["is_best"]].iloc[0]
    fig.add_annotation(
        x=best_row["day_of_week"], y=best_row["avg_price"],
        text=f"Mejor dia<br>${best_row['avg_price']:,.0f}",
        showarrow=True, arrowhead=2, arrowsize=1,
        arrowcolor=COLORS["success"], font=dict(size=11, color=COLORS["success"]), yshift=20,
    )

    fig.update_layout(
        height=380, margin=dict(l=20, r=20, t=10, b=40),
        xaxis_title=None, yaxis_title="Precio promedio (MXN)", yaxis_tickformat="$,.0f",
        showlegend=False, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(gridcolor="rgba(0,0,0,0.05)"), yaxis=dict(gridcolor="rgba(0,0,0,0.05)"),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_variation_histogram(days: int, category_id: int | None = None):
    st.markdown('<div class="section-title">📊 Distribucion de variaciones</div>', unsafe_allow_html=True)

    changes_df = load_price_changes(days=days, category_id=category_id)
    if changes_df.empty:
        st.info("No hay datos de variaciones para este periodo.")
        return

    pcts = changes_df["price_change_pct"].dropna()
    if len(pcts) == 0:
        st.info("No hay variaciones registradas.")
        return

    # Limitar outliers al p5-p95
    p5, p95 = pcts.quantile(0.05), pcts.quantile(0.95)
    filtered_pcts = pcts[(pcts >= p5) & (pcts <= p95)]
    neg_pcts = filtered_pcts[filtered_pcts < 0]
    pos_pcts = filtered_pcts[filtered_pcts >= 0]

    fig = go.Figure()

    if len(neg_pcts) > 0:
        fig.add_trace(go.Histogram(x=neg_pcts, name="Descuento", marker_color=COLORS["success"], opacity=0.8,
                                   hovertemplate="Variacion: %{x:+.2f}%<br>Frecuencia: %{y}<br><extra></extra>"))
    if len(pos_pcts) > 0:
        fig.add_trace(go.Histogram(x=pos_pcts, name="Aumento", marker_color=COLORS["danger"], opacity=0.8,
                                   hovertemplate="Variacion: %{x:+.2f}%<br>Frecuencia: %{y}<br><extra></extra>"))

    fig.add_vline(x=0, line_dash="dash", line_color="rgba(0,0,0,0.4)", line_width=1.5,
                  annotation_text="Sin cambio", annotation_position="top", annotation_font_size=10)

    mean_pct, median_pct = pcts.mean(), pcts.median()
    fig.add_vline(x=mean_pct, line_dash="dot", line_color=COLORS["warning"], line_width=1.5,
                  annotation_text=f"Media: {mean_pct:+.2f}%", annotation_position="top right", annotation_font_size=9)

    fig.update_layout(
        height=400, margin=dict(l=20, r=20, t=30, b=40),
        xaxis_title="Variacion porcentual (%)", yaxis_title="Frecuencia",
        barmode="overlay",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(gridcolor="rgba(0,0,0,0.05)"), yaxis=dict(gridcolor="rgba(0,0,0,0.05)"),
    )
    st.plotly_chart(fig, use_container_width=True)

    col1, col2, col3 = st.columns(3)
    with col1: st.metric("Variacion media", f"{mean_pct:+.2f}%")
    with col2: st.metric("Mediana", f"{median_pct:+.2f}%")
    with col3:
        pct_decreases = (len(neg_pcts) / len(pcts) * 100) if len(pcts) > 0 else 0
        st.metric("Proporcion descensos", f"{pct_decreases:.0f}%")


def _render_category_boxplot(days: int):
    st.markdown('<div class="section-title">📦 Distribucion de precios por categoria</div>', unsafe_allow_html=True)

    stats_df = load_category_price_stats(days=days)
    if stats_df.empty:
        st.info("No hay datos de precios para este periodo.")
        return

    category_order = stats_df.groupby("category_name")["price"].median().sort_values(ascending=True).index.tolist()
    colors = [CATEGORY_COLORS.get(cat, COLORS["primary"]) for cat in category_order]

    fig = go.Figure()
    for idx, cat_name in enumerate(category_order):
        cat_data = stats_df[stats_df["category_name"] == cat_name]
        fig.add_trace(go.Box(
            y=cat_data["price"].tolist(), name=cat_name,
            marker_color=colors[idx], boxmean="sd",
            hovertemplate="<b>%{fullData.name}</b><br>Precio: $%{y:,.0f} MXN<br><extra></extra>",
        ))

    fig.update_layout(
        height=400, margin=dict(l=20, r=20, t=10, b=40),
        yaxis_title="Precio (MXN)", yaxis_tickformat="$,.0f",
        showlegend=False, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(gridcolor="rgba(0,0,0,0.05)"), xaxis=dict(gridcolor="rgba(0,0,0,0.02)"),
    )
    st.plotly_chart(fig, use_container_width=True)
