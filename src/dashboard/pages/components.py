"""Pagina de Componentes: detalle por categoria con tabs, filtros y expanders."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dashboard.common.styles import COLORS, STORE_COLORS
from src.dashboard.common.loaders import (
    load_products_list,
    load_category_summary,
    load_category_price_stats,
    load_most_volatile_products,
    load_product_detail,
)
from src.dashboard.common.utils import get_analytics_service


# Iconos para cada tab de categoria
TAB_ICONS = {
    "CPUs": "🖥️", "GPUs": "🎮", "RAM": "💾", "SSD": "💿",
    "Laptops": "💻", "Monitores": "🖥️", "Placas madre": "🔧",
}


def render():
    """Renderiza la pagina de componentes con tabs por categoria."""
    st.markdown(
        '<h1 style="font-size:1.8rem;font-weight:800;color:#263238;">🔧 Componentes por Categoria</h1>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="font-size:0.9rem;color:#78909C;margin-bottom:1.5rem;">'
        'Detalle de precios y variaciones por tipo de componente</p>',
        unsafe_allow_html=True,
    )

    products_df = load_products_list()
    category_df = load_category_summary()

    if products_df.empty:
        st.warning("⚠️ No hay datos. Ejecuta el pipeline o el script de seed.")
        return

    categories = sorted(products_df["category_name"].unique().tolist())
    tab_labels = [f"{TAB_ICONS.get(c, '📦')} {c}" for c in categories]
    tabs = st.tabs(tab_labels)

    for idx, category_name in enumerate(categories):
        with tabs[idx]:
            _render_category_tab(category_name, products_df, category_df)


def _render_category_tab(category_name: str, products_df: pd.DataFrame, category_df: pd.DataFrame):
    cat_products = products_df[products_df["category_name"] == category_name]
    if cat_products.empty:
        st.info(f"No hay productos en la categoria {category_name}.")
        return

    category_id = int(cat_products["category_id"].iloc[0])

    # KPIs de la categoria
    cat_row = category_df[category_df["category_name"] == category_name]
    if not cat_row.empty:
        row = cat_row.iloc[0]
        col1, col2, col3, col4 = st.columns(4)
        with col1: st.metric("Productos", f"{int(row['product_count'])}", delta=f"en {len(cat_products['store_name'].unique())} tiendas")
        with col2: st.metric("Precio promedio", f"${row['avg_price']:,.0f}")
        with col3: st.metric("Rango de precios", f"${row['min_price']:,.0f} — ${row['max_price']:,.0f}")
        with col4:
            avg_disc = row.get("avg_discount_pct", 0)
            disc_str = f"{avg_disc:+.1f}%" if pd.notna(avg_disc) else "N/A"
            st.metric("Variacion promedio", disc_str, delta_color="inverse" if pd.notna(avg_disc) and avg_disc > 0 else "normal")

    st.markdown("---")

    # Filtros dinamicos
    col_brand, col_store, col_price = st.columns([2, 2, 3])

    with col_brand:
        brands = ["Todas"] + sorted([b for b in cat_products["brand"].dropna().unique() if b])
        selected_brand = st.selectbox("🏷️ Marca", options=brands, index=0, key=f"comp_brand_{category_name}")

    with col_store:
        stores = ["Todas"] + sorted(cat_products["store_name"].unique().tolist())
        selected_store = st.selectbox("🏪 Tienda", options=stores, index=0, key=f"comp_store_{category_name}")

    with col_price:
        price_stats = load_category_price_stats(days=30)
        cat_prices = price_stats[price_stats["category_name"] == category_name]
        if not cat_prices.empty:
            p_min, p_max = float(cat_prices["price"].min()), float(cat_prices["price"].max())
        else:
            p_min, p_max = 0.0, 50000.0
        price_range = st.slider(
            "💰 Rango de precio (MXN)", min_value=p_min, max_value=p_max,
            value=(p_min, p_max), key=f"comp_price_{category_name}", format="$%,.0f",
        )

    # Tabla filtrada — merge por nombre de producto
    if not cat_prices.empty and "product_name" in cat_prices.columns:
        latest_by_product = cat_prices.groupby("product_name")["price"].first().reset_index().rename(columns={"price": "current_price", "product_name": "name"})
        filtered = cat_products.merge(latest_by_product, on="name", how="left")
    else:
        filtered = cat_products.copy()
        filtered["current_price"] = 0.0

    if selected_brand != "Todas":
        filtered = filtered[filtered["brand"] == selected_brand]
    if selected_store != "Todas":
        filtered = filtered[filtered["store_name"] == selected_store]
    if not filtered.empty and "current_price" in filtered.columns:
        filtered = filtered[(filtered["current_price"] >= price_range[0]) & (filtered["current_price"] <= price_range[1])]

    st.markdown(
        f'<div class="section-title">📋 Productos en {category_name} ({len(filtered)} resultados)</div>',
        unsafe_allow_html=True,
    )

    if filtered.empty:
        st.info("No hay productos que coincidan con los filtros.")
    else:
        display_df = filtered.copy()
        if "current_price" in display_df.columns:
            display_df["Precio"] = display_df["current_price"].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "N/A")
        else:
            display_df["Precio"] = "N/A"
        display_df["Marca"] = display_df["brand"].fillna("Sin marca")

        table_cols = ["name", "Marca", "store_name", "Precio"]
        available_cols = [c for c in table_cols if c in display_df.columns]
        st.dataframe(
            display_df[available_cols].rename(columns={"name": "Producto", "store_name": "Tienda"}),
            use_container_width=True,
            height=min(300, 45 + 35 * min(len(display_df), 8)),
            hide_index=True,
            column_config={
                "Producto": st.column_config.TextColumn(width="large"),
                "Marca": st.column_config.TextColumn(width="small"),
                "Tienda": st.column_config.TextColumn(width="small"),
                "Precio": st.column_config.TextColumn(width="small"),
            },
        )

        # Expanders
        st.markdown('<div class="section-title">🔍 Detalle de producto</div>', unsafe_allow_html=True)
        store_icons = {"Mercado Libre": "🟡", "AliExpress": "🔴", "Temu": "🟠"}
        for _, prod_row in filtered.head(10).iterrows():
            prod_id = int(prod_row["id"])
            prod_name = prod_row["name"]
            store = prod_row["store_name"]
            brand = prod_row.get("brand", "")
            brand_str = f" — {brand}" if pd.notna(brand) and brand else ""
            icon = store_icons.get(store, "🟢")
            with st.expander(f"{icon} {prod_name[:60]}{brand_str} ({store})"):
                _render_product_expander(prod_id, prod_name, store)

    st.markdown("---")

    # Volatilidad + mejor momento
    col_volatile, col_best_time = st.columns([3, 2])
    with col_volatile:
        _render_volatile_products_chart(category_id, category_name)
    with col_best_time:
        _render_best_time_indicator(category_id, category_name)


def _render_product_expander(product_id: int, product_name: str, store_name: str):
    detail_df = load_product_detail(product_id=product_id, days=30)
    if detail_df.empty:
        st.info("No hay datos historicos para este producto.")
        return

    current_price = detail_df["price"].iloc[-1]
    min_price = detail_df["price"].min()
    max_price = detail_df["price"].max()
    last_change = detail_df["price_change_pct"].iloc[-1]
    last_change_str = f"{last_change:+.2f}%" if pd.notna(last_change) else "N/A"

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1: st.metric("Precio actual", f"${current_price:,.2f}")
    with kpi2: st.metric("Minimo", f"${min_price:,.2f}")
    with kpi3: st.metric("Maximo", f"${max_price:,.2f}")
    with kpi4:
        delta_color = "inverse" if pd.notna(last_change) and last_change > 0 else "normal"
        st.metric("Ultima variacion", last_change_str, delta_color=delta_color)

    # Mini grafico
    store_color = STORE_COLORS.get(store_name, COLORS["primary"])
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=detail_df["date"], y=detail_df["price"],
        mode="lines+markers", name="Precio",
        line=dict(color=store_color, width=2),
        marker=dict(size=5),
        fill="tozeroy",
        fillcolor=f"rgba({int(store_color[1:3], 16)},{int(store_color[3:5], 16)},{int(store_color[5:7], 16)},0.08)",
        hovertemplate="Fecha: %{x}<br>Precio: $%{y:,.2f} MXN<br><extra></extra>",
    ))
    fig.add_hline(y=min_price, line_dash="dot", line_color=COLORS["success"], opacity=0.5,
                  annotation_text=f"Min: ${min_price:,.0f}", annotation_position="bottom right", annotation_font_size=9)
    fig.add_hline(y=max_price, line_dash="dot", line_color=COLORS["danger"], opacity=0.5,
                  annotation_text=f"Max: ${max_price:,.0f}", annotation_position="top right", annotation_font_size=9)

    fig.update_layout(
        height=250, margin=dict(l=20, r=20, t=10, b=30),
        xaxis_title=None, yaxis_title="Precio (MXN)", yaxis_tickformat="$,.0f",
        showlegend=False, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(gridcolor="rgba(0,0,0,0.05)"), yaxis=dict(gridcolor="rgba(0,0,0,0.05)"),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Historial reciente
    recent = detail_df.tail(5).copy()
    recent["Fecha"] = pd.to_datetime(recent["date"]).dt.strftime("%d/%m/%Y")
    recent["Precio"] = recent["price"].apply(lambda x: f"${x:,.2f}")
    recent["Variacion"] = recent["price_change_pct"].apply(lambda x: f"{x:+.2f}%" if pd.notna(x) else "—")
    recent["Disponible"] = recent["availability"].apply(lambda x: "✅ Si" if x else "❌ No")
    st.dataframe(
        recent[["Fecha", "Precio", "Variacion", "Disponible"]],
        use_container_width=True, hide_index=True,
        height=min(180, 45 + 35 * len(recent)),
    )


def _render_volatile_products_chart(category_id: int, category_name: str):
    st.markdown('<div class="section-title">📊 Productos mas volatiles</div>', unsafe_allow_html=True)

    volatile_df = load_most_volatile_products(category_id=category_id, top_n=5)
    if volatile_df.empty:
        st.info("No hay suficientes datos de volatilidad para esta categoria.")
        return

    service = get_analytics_service()
    fig = go.Figure()

    for _, row in volatile_df.iterrows():
        pid = int(row["product_id"])
        prod_name = row["product_name"]
        store = row["store_name"]
        volatility = row["volatility"]
        evo_df = service.get_price_evolution(product_id=pid, days=30)
        if evo_df.empty:
            continue

        store_color = STORE_COLORS.get(store, COLORS["primary"])
        display_name = prod_name[:35] + "..." if len(prod_name) > 35 else prod_name
        fig.add_trace(go.Scatter(
            x=evo_df["date"], y=evo_df["price"],
            mode="lines+markers", name=display_name,
            line=dict(color=store_color, width=2), marker=dict(size=5),
            hovertemplate=(
                f"<b>{prod_name[:50]}</b><br>Fecha: %{x}<br>Precio: $%{y:,.2f} MXN<br>"
                f"Volatilidad: {volatility:.2f}<br><extra></extra>"
            ),
        ))

    fig.update_layout(
        height=380, margin=dict(l=20, r=20, t=30, b=40),
        xaxis_title="Fecha", yaxis_title="Precio (MXN)", yaxis_tickformat="$,.0f",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=9)),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(gridcolor="rgba(0,0,0,0.05)"), yaxis=dict(gridcolor="rgba(0,0,0,0.05)"),
        title=dict(text=f"Top 5 productos con mayor variacion en {category_name}", font=dict(size=12, color="#78909C"), x=0, xanchor="left", yanchor="top"),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Mini tabla de volatilidad
    vol_display = volatile_df.copy()
    vol_display["Producto"] = vol_display["product_name"].apply(lambda x: x[:40] + "..." if len(x) > 40 else x)
    vol_display["Tienda"] = vol_display["store_name"]
    vol_display["Volatilidad"] = vol_display["volatility"].apply(lambda x: f"{x:.2f}")
    vol_display["Var. prom."] = vol_display["avg_change_pct"].apply(lambda x: f"{x:+.2f}%")
    vol_display["Precio actual"] = vol_display["current_price"].apply(lambda x: f"${x:,.0f}")

    st.dataframe(
        vol_display[["Producto", "Tienda", "Volatilidad", "Var. prom.", "Precio actual"]],
        use_container_width=True, hide_index=True,
        height=min(200, 45 + 35 * len(vol_display)),
        column_config={
            "Producto": st.column_config.TextColumn(width="large"),
            "Tienda": st.column_config.TextColumn(width="small"),
            "Volatilidad": st.column_config.TextColumn(width="small", help="Desviacion estandar de variaciones %"),
            "Var. prom.": st.column_config.TextColumn(width="small", help="Variacion promedio del precio (%)"),
            "Precio actual": st.column_config.TextColumn(width="small"),
        },
    )


def _render_best_time_indicator(category_id: int, category_name: str):
    st.markdown('<div class="section-title">🗓️ Mejor momento para comprar</div>', unsafe_allow_html=True)

    service = get_analytics_service()
    btb_df = service.get_best_time_to_buy(category_id=category_id, days=90)

    if btb_df.empty:
        st.info("No hay datos suficientes para este analisis.")
        return

    colors = [COLORS["success"] if is_best else COLORS["primary"] for is_best in btb_df["is_best"]]

    fig = go.Figure(go.Bar(
        x=btb_df["day_of_week"], y=btb_df["avg_price"],
        marker_color=colors,
        marker_line_color="rgba(0,0,0,0.1)", marker_line_width=1,
        text=[f"${p:,.0f}" for p in btb_df["avg_price"]],
        textposition="auto", textfont=dict(size=9, color="white"),
        hovertemplate=(
            "<b>%{x}</b><br>Precio promedio: $%{y:,.0f} MXN<br>"
            "Min: $%{customdata[0]:,.0f} | Max: $%{customdata[1]:,.0f}<br>Registros: %{customdata[2]}<br><extra></extra>"
        ),
        customdata=list(zip(btb_df["min_price"], btb_df["max_price"], btb_df["price_records"])),
    ))

    best_row = btb_df[btb_df["is_best"]].iloc[0]
    best_day = best_row["day_of_week"]
    best_price = best_row["avg_price"]

    fig.add_annotation(
        x=best_day, y=best_price, text=f"Mejor dia<br>${best_price:,.0f}",
        showarrow=True, arrowhead=2, arrowsize=1,
        arrowcolor=COLORS["success"], font=dict(size=10, color=COLORS["success"]), yshift=20,
    )

    fig.update_layout(
        height=350, margin=dict(l=20, r=20, t=30, b=40),
        xaxis_title=None, yaxis_title="Precio promedio (MXN)", yaxis_tickformat="$,.0f",
        showlegend=False, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(gridcolor="rgba(0,0,0,0.02)"), yaxis=dict(gridcolor="rgba(0,0,0,0.05)"),
        title=dict(text=f"Patron semanal en {category_name}", font=dict(size=12, color="#78909C"), x=0, xanchor="left", yanchor="top"),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Recomendacion estilizada
    worst_row = btb_df.loc[btb_df["avg_price"].idxmax()]
    savings_pct = ((worst_row["avg_price"] - best_price) / worst_row["avg_price"] * 100) if worst_row["avg_price"] > 0 else 0

    st.markdown(
        f'<div style="background:#E8F5E9;border-left:4px solid {COLORS["success"]};'
        f'padding:0.8rem 1rem;border-radius:8px;margin-top:0.5rem;">'
        f'<span style="font-size:0.8rem;color:#78909C;">Recomendacion</span><br>'
        f'<span style="font-size:1.1rem;font-weight:700;color:#263238;">'
        f'Compra los {category_name} el <b>{best_day}</b></span><br>'
        f'<span style="font-size:0.85rem;color:#546E7A;">'
        f'Precio promedio: ${best_price:,.0f} — '
        f'Ahorro potencial: {savings_pct:.1f}% vs {worst_row["day_of_week"]} '
        f'(${worst_row["avg_price"]:,.0f})</span></div>',
        unsafe_allow_html=True,
    )
