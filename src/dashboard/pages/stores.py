"""Pagina de Tiendas: ranking, comparativa, market share."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dashboard.common.styles import COLORS, STORE_COLORS
from src.dashboard.common.loaders import (
    load_store_ranking,
    load_store_category_comparison,
    load_store_detailed_stats,
    load_products_list,
)


def render():
    """Renderiza la pagina de tiendas con ranking y comparacion."""
    st.markdown(
        '<h1 style="font-size:1.8rem;font-weight:800;color:#263238;">🏪 Comparacion de Tiendas</h1>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="font-size:0.9rem;color:#78909C;margin-bottom:1.5rem;">'
        'Compara el desempeno de cada tienda en terminos de precios y cobertura</p>',
        unsafe_allow_html=True,
    )

    ranking_df = load_store_ranking()
    comparison_df = load_store_category_comparison()
    stats_df = load_store_detailed_stats()

    if ranking_df.empty:
        st.warning("⚠️ No hay datos de tiendas. Ejecuta el pipeline o el script de seed.")
        return

    # Filtro de categoria
    categories = ["Todas"] + sorted(comparison_df["category_name"].unique().tolist())
    selected_category = st.selectbox("📂 Filtrar por categoria", options=categories, index=0, key="stores_category_filter")

    st.markdown("---")

    # 1. Ranking
    _render_store_ranking_chart(ranking_df, selected_category)
    st.markdown("---")

    # 2. Barras agrupadas
    _render_store_category_comparison_chart(comparison_df, selected_category)
    st.markdown("---")

    # 3. Pie + KPIs
    col_pie, col_kpis = st.columns([2, 1])
    with col_pie:
        _render_market_share_pie(ranking_df)
    with col_kpis:
        _render_store_kpis(ranking_df)
    st.markdown("---")

    # 4. Tabla detallada
    _render_store_stats_table(stats_df)


def _render_store_ranking_chart(ranking_df: pd.DataFrame, selected_category: str):
    st.markdown('<div class="section-title">🏆 Ranking de tiendas por precio promedio</div>', unsafe_allow_html=True)

    if selected_category != "Todas":
        products_df = load_products_list()
        cat_products = products_df[products_df["category_name"] == selected_category]
        if not cat_products.empty:
            category_id = int(cat_products["category_id"].iloc[0])
            ranking_df = load_store_ranking(category_id=category_id)
        else:
            ranking_df = pd.DataFrame()

    if ranking_df.empty:
        st.info("No hay datos de ranking para esta categoria.")
        return

    df_sorted = ranking_df.sort_values("avg_price", ascending=True)
    colors = [STORE_COLORS.get(store, COLORS["primary"]) for store in df_sorted["store_name"]]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=df_sorted["store_name"], x=df_sorted["avg_price"], orientation="h",
        marker_color=colors, marker_line_color="rgba(0,0,0,0.15)", marker_line_width=1.5,
        text=[f"${p:,.0f} MXN" for p in df_sorted["avg_price"]],
        textposition="auto", textfont=dict(size=13, color="#263238"),
        hovertemplate=(
            "<b>%{y}</b><br>Precio promedio: $%{x:,.0f} MXN<br>"
            "Rango: $%{customdata[0]:,.0f} — $%{customdata[1]:,.0f}<br>Productos: %{customdata[2]}<br><extra></extra>"
        ),
        customdata=list(zip(df_sorted["min_price"], df_sorted["max_price"], df_sorted["product_count"])),
    ))

    # Marcar la mas barata
    cheapest = df_sorted.iloc[-1] if len(df_sorted) > 0 else None
    if cheapest is not None:
        fig.add_annotation(
            x=cheapest["avg_price"], y=cheapest["store_name"],
            text=" Mejor precio", showarrow=True, arrowhead=2, arrowsize=1,
            arrowcolor=COLORS["success"], font=dict(size=11, color=COLORS["success"]),
            xanchor="left", yanchor="middle",
        )

    cat_suffix = f" — {selected_category}" if selected_category != "Todas" else ""
    fig.update_layout(
        height=max(250, 80 + 60 * len(df_sorted)),
        margin=dict(l=20, r=40, t=30, b=40),
        xaxis_title="Precio promedio (MXN)", yaxis_title=None,
        xaxis_tickformat="$,.0f", showlegend=False,
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(gridcolor="rgba(0,0,0,0.05)"), yaxis=dict(gridcolor="rgba(0,0,0,0.02)"),
        title=dict(text=f"Precio promedio por tienda{cat_suffix}", font=dict(size=13, color="#78909C"), x=0, xanchor="left", yanchor="top"),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Metricas rapidas
    if len(df_sorted) >= 2:
        cheapest_price = df_sorted.iloc[-1]["avg_price"]
        most_expensive_price = df_sorted.iloc[0]["avg_price"]
        price_gap = most_expensive_price - cheapest_price
        gap_pct = (price_gap / most_expensive_price * 100) if most_expensive_price else 0

        col1, col2, col3 = st.columns(3)
        with col1: st.metric("Mas barata", f"${cheapest_price:,.0f}", delta=df_sorted.iloc[-1]["store_name"])
        with col2: st.metric("Mas cara", f"${most_expensive_price:,.0f}", delta=df_sorted.iloc[0]["store_name"], delta_color="inverse")
        with col3: st.metric("Diferencia", f"${price_gap:,.0f}", delta=f"{gap_pct:.1f}% mas cara", delta_color="inverse")


def _render_store_category_comparison_chart(comparison_df: pd.DataFrame, selected_category: str):
    st.markdown('<div class="section-title">📊 Precio promedio por categoria y tienda</div>', unsafe_allow_html=True)

    df = comparison_df[comparison_df["category_name"] == selected_category] if selected_category != "Todas" else comparison_df
    if df.empty:
        st.info("No hay datos de comparacion disponibles.")
        return

    fig = go.Figure()
    stores = sorted(df["store_name"].unique())

    for store in stores:
        store_data = df[df["store_name"] == store].sort_values("category_name")
        store_color = STORE_COLORS.get(store, COLORS["primary"])
        fig.add_trace(go.Bar(
            name=store,
            x=store_data["category_name"], y=store_data["avg_price"],
            marker_color=store_color, marker_line_color="rgba(0,0,0,0.1)", marker_line_width=1,
            text=[f"${p:,.0f}" for p in store_data["avg_price"]],
            textposition="auto", textfont=dict(size=9, color="white"),
            hovertemplate=(
                "<b>%{x}</b> — " + store + "<br>Precio promedio: $%{y:,.0f} MXN<br>Productos: %{customdata[0]}<br><extra></extra>"
            ),
            customdata=list(zip(store_data["product_count"])),
        ))

    fig.update_layout(
        barmode="group", height=450, margin=dict(l=20, r=20, t=30, b=50),
        xaxis_title=None, yaxis_title="Precio promedio (MXN)", yaxis_tickformat="$,.0f",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=11)),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(gridcolor="rgba(0,0,0,0.02)", tickangle=-15),
        yaxis=dict(gridcolor="rgba(0,0,0,0.05)"),
        bargap=0.15, bargroupgap=0.1,
        title=dict(text="Desglose por categoria y tienda", font=dict(size=13, color="#78909C"), x=0, xanchor="left", yanchor="top"),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Insight: tienda mas barata por categoria
    if selected_category == "Todas" and not comparison_df.empty:
        st.markdown('<div class="section-title">💡 Tienda mas barata por categoria</div>', unsafe_allow_html=True)
        best_by_cat = comparison_df.sort_values("avg_price").groupby("category_name").first().reset_index()
        cols = st.columns(min(len(best_by_cat), 4))
        for idx, (_, row) in enumerate(best_by_cat.iterrows()):
            with cols[idx % len(cols)]:
                store_color = STORE_COLORS.get(row["store_name"], COLORS["primary"])
                st.markdown(
                    f'<div style="border-left:3px solid {store_color};padding-left:8px;margin:0.3rem 0;">'
                    f'<span style="font-size:0.75rem;color:#78909C;">{row["category_name"]}</span><br>'
                    f'<span style="font-size:0.9rem;font-weight:600;">{row["store_name"]}</span><br>'
                    f'<span style="font-size:1.1rem;font-weight:700;">${row["avg_price"]:,.0f}</span> '
                    f'<span style="font-size:0.75rem;">({int(row["product_count"])} prod.)</span></div>',
                    unsafe_allow_html=True,
                )


def _render_market_share_pie(ranking_df: pd.DataFrame):
    st.markdown('<div class="section-title">🥧 Participacion de mercado</div>', unsafe_allow_html=True)
    if ranking_df.empty:
        st.info("No hay datos de participacion.")
        return

    colors = [STORE_COLORS.get(store, COLORS["primary"]) for store in ranking_df["store_name"]]

    fig = go.Figure(go.Pie(
        labels=ranking_df["store_name"], values=ranking_df["product_count"],
        marker_colors=colors, marker_line_color="white", marker_line_width=2,
        textinfo="label+percent", textfont=dict(size=12),
        hovertemplate="<b>%{label}</b><br>Productos: %{value}<br>Participacion: %{percent}<br><extra></extra>",
        hole=0.35,
    ))

    fig.update_layout(
        height=380, margin=dict(l=20, r=20, t=30, b=20),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.15, xanchor="center", x=0.5, font=dict(size=11)),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        title=dict(text="Productos monitoreados por tienda", font=dict(size=13, color="#78909C"), x=0, xanchor="left", yanchor="top"),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_store_kpis(ranking_df: pd.DataFrame):
    st.markdown('<div class="section-title">📋 Resumen de cobertura</div>', unsafe_allow_html=True)
    if ranking_df.empty:
        return

    total_products = int(ranking_df["product_count"].sum())
    total_stores = len(ranking_df)
    avg_price_global = ranking_df["avg_price"].mean()
    top_store = ranking_df.loc[ranking_df["product_count"].idxmax()]

    st.metric("Productos totales", f"{total_products:,}", delta=f"{total_stores} tiendas activas")
    st.markdown("<div style='height:0.8rem'></div>", unsafe_allow_html=True)
    st.metric("Precio promedio global", f"${avg_price_global:,.0f} MXN")
    st.markdown("<div style='height:0.8rem'></div>", unsafe_allow_html=True)

    store_color = STORE_COLORS.get(top_store["store_name"], COLORS["primary"])
    st.markdown(
        f'<div style="background:{store_color}15;border-left:3px solid {store_color};'
        f'padding:0.6rem 0.8rem;border-radius:8px;margin-top:0.5rem;">'
        f'<span style="font-size:0.75rem;color:#78909C;">Mayor cobertura</span><br>'
        f'<span style="font-size:1rem;font-weight:700;color:#263238;">{top_store["store_name"]}</span><br>'
        f'<span style="font-size:0.85rem;">{int(top_store["product_count"])} productos '
        f'({int(top_store["product_count"])/total_products*100:.0f}%)</span></div>',
        unsafe_allow_html=True,
    )


def _render_store_stats_table(stats_df: pd.DataFrame):
    st.markdown('<div class="section-title">📋 Estadisticas detalladas por tienda</div>', unsafe_allow_html=True)
    if stats_df.empty:
        st.info("No hay estadisticas detalladas.")
        return

    display_df = stats_df.copy()
    display_df["Precio min"] = display_df["min_price"].apply(lambda x: f"${x:,.2f}")
    display_df["Precio max"] = display_df["max_price"].apply(lambda x: f"${x:,.2f}")
    display_df["Precio promedio"] = display_df["avg_price"].apply(lambda x: f"${x:,.2f}")

    if "last_update" in display_df.columns:
        display_df["Ultima actualizacion"] = display_df["last_update"].apply(
            lambda x: pd.to_datetime(x).strftime("%d/%m/%Y %H:%M") if pd.notna(x) else "Sin datos"
        )
    else:
        display_df["Ultima actualizacion"] = "Sin datos"

    display_df = display_df[[
        "store_name", "Precio min", "Precio max", "Precio promedio",
        "product_count", "category_count", "Ultima actualizacion",
    ]].rename(columns={"store_name": "Tienda", "product_count": "Productos", "category_count": "Categorias"})
    display_df.insert(0, "#", range(1, len(display_df) + 1))

    st.dataframe(
        display_df, use_container_width=True,
        height=min(300, 45 + 45 * len(display_df)),
        column_config={
            "#": st.column_config.NumberColumn(width="tiny"),
            "Tienda": st.column_config.TextColumn(width="medium"),
            "Precio min": st.column_config.TextColumn(width="small"),
            "Precio max": st.column_config.TextColumn(width="small"),
            "Precio promedio": st.column_config.TextColumn(width="small"),
            "Productos": st.column_config.NumberColumn(width="small"),
            "Categorias": st.column_config.NumberColumn(width="small", help="Categorias con productos monitoreados"),
            "Ultima actualizacion": st.column_config.TextColumn(width="medium", help="Fecha del ultimo registro"),
        },
        hide_index=True,
    )
