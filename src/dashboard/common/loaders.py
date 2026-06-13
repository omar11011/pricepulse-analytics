"""Data loaders con cache para el dashboard."""

import pandas as pd
import streamlit as st

from src.analytics.queries import AnalyticsService
from src.dashboard.common.utils import get_analytics_service


# Cada loader wraps un metodo de AnalyticsService con st.cache_data(ttl=300)
# asi evitamos pegarle a la BD en cada rerun

@st.cache_data(ttl=300)
def load_kpi_summary() -> pd.DataFrame:
    service = get_analytics_service()
    return service.get_kpi_summary()

@st.cache_data(ttl=300)
def load_category_summary() -> pd.DataFrame:
    service = get_analytics_service()
    return service.get_category_summary()

@st.cache_data(ttl=300)
def load_top_discounts(n: int = 10) -> pd.DataFrame:
    service = get_analytics_service()
    return service.get_top_discounts(n=n)

@st.cache_data(ttl=300)
def load_store_ranking(category_id: int | None = None) -> pd.DataFrame:
    service = get_analytics_service()
    return service.get_store_ranking(category_id=category_id)

@st.cache_data(ttl=300)
def load_category_volatility(days: int = 30) -> pd.DataFrame:
    service = get_analytics_service()
    return service.get_category_volatility(days=days)

@st.cache_data(ttl=300)
def load_price_evolution(product_id: int, days: int = 30) -> pd.DataFrame:
    service = get_analytics_service()
    return service.get_price_evolution(product_id=product_id, days=days)

@st.cache_data(ttl=300)
def load_products_list(category_id: int | None = None) -> pd.DataFrame:
    service = get_analytics_service()
    return service.get_products_list(category_id=category_id)

@st.cache_data(ttl=300)
def load_price_changes(days: int = 30, category_id: int | None = None) -> pd.DataFrame:
    service = get_analytics_service()
    return service.get_price_changes(days=days, category_id=category_id)

@st.cache_data(ttl=300)
def load_category_price_stats(days: int = 30) -> pd.DataFrame:
    service = get_analytics_service()
    return service.get_category_price_stats(days=days)

@st.cache_data(ttl=300)
def load_store_category_comparison() -> pd.DataFrame:
    service = get_analytics_service()
    return service.get_store_category_comparison()

@st.cache_data(ttl=300)
def load_store_detailed_stats() -> pd.DataFrame:
    service = get_analytics_service()
    return service.get_store_detailed_stats()

@st.cache_data(ttl=300)
def load_most_volatile_products(category_id: int, top_n: int = 5) -> pd.DataFrame:
    service = get_analytics_service()
    return service.get_most_volatile_products(category_id=category_id, top_n=top_n)

@st.cache_data(ttl=300)
def load_product_detail(product_id: int, days: int = 30) -> pd.DataFrame:
    service = get_analytics_service()
    return service.get_product_detail(product_id=product_id, days=days)
