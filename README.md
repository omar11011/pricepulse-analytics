<div align="center">

<img src="docs/favicon.png" width="120" height="120" alt="PricePulse Analytics Logo" />

# PricePulse Analytics

**Plataforma de ingeniería de datos para monitoreo de precios tecnológicos en el mercado mexicano**

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.37+-FF4B4B?style=flat-square&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)
[![Plotly](https://img.shields.io/badge/Plotly-5.22+-3F4F75?style=flat-square&logo=plotly&logoColor=white)](https://plotly.com/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00?style=flat-square)](https://www.sqlalchemy.org/)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

[🚀 Quick Start](#-quick-start) · [📐 Arquitectura](#-arquitectura) · [📊 Dashboard](#-dashboard) · [🧩 Módulos](#-módulos) · [🐳 Docker](#-docker) · [⚙️ Configuración](#️-configuración)

</div>

---

## Descripción

**PricePulse Analytics** es una plataforma de ingeniería de datos que monitorea precios de productos tecnológicos en tres tiendas online — **Mercado Libre**, **AliExpress** y **Temu** — y los presenta en un dashboard interactivo con métricas de negocio, tendencias y recomendaciones de compra.

El sistema implementa un pipeline ETL completo (Extract → Transform → Load) con scraping adaptativo por tienda, transformación y limpieza de datos con Pandas, almacenamiento dual SQLite/PostgreSQL, y un dashboard analítico con 4 páginas y 15 consultas de negocio optimizadas.

| Característica | Detalle |
|---|---|
| **Tiendas monitoreadas** | Mercado Libre, AliExpress, Temu |
| **Categorías** | CPUs, GPUs, RAM, SSD, Laptops, Monitores, Placas madre |
| **Productos en BD** | 105 productos con 426 registros de precios |
| **Dashboard** | 4 páginas: Inicio, Tendencias, Tiendas, Componentes |
| **Base de datos** | SQLite (desarrollo) / PostgreSQL (producción) |
| **Despliegue** | Docker Compose / Streamlit Community Cloud |

---

## 🚀 Quick Start

### Con Docker (recomendado)

```bash
git clone https://github.com/omar11011/pricepulse-analytics.git
cd pricepulse-analytics
cp .env.docker .env
docker compose up
```

Abre **http://localhost:8501** en tu navegador. El sistema automáticamente:
1. Levanta PostgreSQL con healthcheck
2. Crea las tablas vía SQLAlchemy `init_db()`
3. Ejecuta el script de datos semilla (`seed_data.py`)
4. Lanza el dashboard Streamlit

### Sin Docker (desarrollo local con SQLite)

```bash
git clone https://github.com/omar11011/pricepulse-analytics.git
cd pricepulse-analytics

# Crear entorno virtual
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Instalar dependencias
pip install -r requirements.txt

# Crear BD SQLite con datos de demostración
python scripts/setup_demo.py

# Lanzar dashboard
streamlit run src/dashboard/app.py
```

---

## 📐 Arquitectura

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PricePulse Analytics                                 │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                      CAPA DE EXTRACCIÓN                             │    │
│  │  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐      │    │
│  │  │  Mercado Libre   │ │   AliExpress    │ │      Temu       │      │    │
│  │  │  requests+BS4    │ │  Playwright     │ │  Playwright     │      │    │
│  │  │  (server-side)   │ │  (JS-rendered)  │ │  (stealth mode) │      │    │
│  │  └────────┬────────┘ └────────┬────────┘ └────────┬────────┘      │    │
│  │           │                    │                    │               │    │
│  │           └────────────────────┼────────────────────┘               │    │
│  │                                ▼                                    │    │
│  │                    ScrapeResult (dataclass)                         │    │
│  └───────────────────────────────┬─────────────────────────────────────┘    │
│                                  │                                          │
│  ┌───────────────────────────────▼─────────────────────────────────────┐    │
│  │                    CAPA DE TRANSFORMACIÓN                           │    │
│  │  ┌──────────────────────┐  ┌───────────────────────────────┐       │    │
│  │  │    DataCleaner       │  │      PriceCalculator          │       │    │
│  │  │  7-step Pandas ETL   │  │  3 modos de cálculo           │       │    │
│  │  │  • Normalizar nombres│  │  • DataFrame diff/pct_change  │       │    │
│  │  │  • Mapear categorías │  │  • vs BD individual           │       │    │
│  │  │  • Convertir USD→MXN │  │  • vs BD batch (1 query)      │       │    │
│  │  │  • Deduplicar        │  │  Pre-computado → consultas O(1)│       │    │
│  │  │  • Validar precios   │  │                               │       │    │
│  │  └──────────┬───────────┘  └──────────────┬────────────────┘       │    │
│  └─────────────┼─────────────────────────────┼────────────────────────┘    │
│                │                             │                             │
│  ┌─────────────▼─────────────────────────────▼────────────────────────┐    │
│  │                    CAPA DE ORQUESTACIÓN                             │    │
│  │                     PricePulsePipeline                             │    │
│  │  Extract → Transform → Load  (resiliente: partial_success)         │    │
│  │  • Upsert productos por (name, store_id)                          │    │
│  │  • Dedup precios por (product_id, scraped_at)                     │    │
│  └─────────────────────────────┬──────────────────────────────────────┘    │
│                                │                                           │
│  ┌─────────────────────────────▼──────────────────────────────────────┐    │
│  │                    CAPA DE ALMACENAMIENTO                           │    │
│  │               SQLAlchemy ORM (dual dialect)                        │    │
│  │  ┌────────────────────┐    ┌─────────────────────────┐            │    │
│  │  │      SQLite        │    │      PostgreSQL          │            │    │
│  │  │  • WAL mode        │    │  • pool_pre_ping         │            │    │
│  │  │  • FK activas      │    │  • pool_size=5           │            │    │
│  │  │  • busy_timeout=5s │    │  • max_overflow=10       │            │    │
│  │  │  • 0 configuración │    │  • Alta concurrencia     │            │    │
│  │  └────────────────────┘    └─────────────────────────┘            │    │
│  │  5 tablas: stores, categories, products, price_history,           │    │
│  │            pipeline_logs                                          │    │
│  └─────────────────────────────┬──────────────────────────────────────┘    │
│                                │                                           │
│  ┌─────────────────────────────▼──────────────────────────────────────┐    │
│  │                    CAPA DE ANALYTICS                                │    │
│  │                    AnalyticsService                                │    │
│  │  15 métodos de consulta → DataFrame                               │    │
│  │  • SQL cross-dialect: strftime/EXTRACT, STDDEV/estadísticos       │    │
│  │  • KPIs, volatilidad, mejores momentos, comparativas              │    │
│  └─────────────────────────────┬──────────────────────────────────────┘    │
│                                │                                           │
│  ┌─────────────────────────────▼──────────────────────────────────────┐    │
│  │                    CAPA DE PRESENTACIÓN                            │    │
│  │                 Streamlit + Plotly Dashboard                        │    │
│  │  ┌──────────┐ ┌────────────┐ ┌──────────┐ ┌──────────────┐       │    │
│  │  │  Inicio  │ │ Tendencias │ │  Tiendas │ │  Componentes │       │    │
│  │  │  KPIs    │ │ Evolución  │ │ Ranking  │ │ Por categoría│       │    │
│  │  │  Resumen │ │ Volatil.   │ │ Market   │ │ Filtros      │       │    │
│  │  │  Top 10  │ │ Mejor hora │ │ share    │ │ Expanders    │       │    │
│  │  └──────────┘ └────────────┘ └──────────┘ └──────────────┘       │    │
│  └───────────────────────────────────────────────────────────────────┘    │
│                                                                           │
│  Config: .env → Settings (frozen dataclasses) → todos los módulos        │
│  Deploy: Docker Compose (PG+Streamlit) | Streamlit Cloud (SQLite)        │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 📊 Flujo de Datos

```
                TIENDAS ONLINE
            ┌────────┬────────┬────────┐
            │  M.L.  │ AliExp.│  Temu  │
            └───┬────┴───┬────┴───┬────┘
                │        │        │
    ┌───────────▼────────▼────────▼───────────┐
    │          EXTRACT (Scrapers)              │
    │                                          │
    │  ML: requests + BeautifulSoup            │
    │  AE: Playwright headless (JS rendering)  │
    │  Temu: Playwright stealth (anti-bot)     │
    │                                          │
    │  → ScrapeResult(name, brand, price,      │
    │     currency, url, store, category)      │
    └──────────────────┬───────────────────────┘
                       │
    ┌──────────────────▼───────────────────────┐
    │         TRANSFORM (Transformers)         │
    │                                          │
    │  DataCleaner (7 pasos Pandas):           │
    │  1. Normalizar nombres de producto       │
    │  2. Mapear categorías a IDs              │
    │  3. Mapear tiendas a IDs                 │
    │  4. Convertir USD → MXN (tasa 17.50)     │
    │  5. Eliminar duplicados                  │
    │  6. Validar rangos de precio             │
    │  7. Pipeline secuencial clean_all()      │
    │                                          │
    │  PriceCalculator (3 modos):              │
    │  • price_change = actual - anterior      │
    │  • price_change_pct = var% relativa      │
    │  → Pre-computado en BD para O(1)         │
    └──────────────────┬───────────────────────┘
                       │
    ┌──────────────────▼───────────────────────┐
    │           LOAD (Pipeline ETL)            │
    │                                          │
    │  Upsert productos (name, store_id)       │
    │  Dedup precios (product_id, scraped_at)  │
    │  Log de ejecución en pipeline_logs       │
    └──────────────────┬───────────────────────┘
                       │
    ┌──────────────────▼───────────────────────┐
    │      ANALYTICS (AnalyticsService)        │
    │                                          │
    │  15 consultas de negocio → DataFrame     │
    │  SQL cross-dialect (SQLite ↔ PostgreSQL) │
    └──────────────────┬───────────────────────┘
                       │
    ┌──────────────────▼───────────────────────┐
    │     PRESENTACIÓN (Streamlit Dashboard)   │
    │                                          │
    │  4 páginas interactivas con Plotly       │
    │  st.cache_data(ttl=300s) para rapidez    │
    └──────────────────────────────────────────┘
```

---

## 📊 Dashboard

### Página de Inicio — KPIs y Resumen General

```
┌──────────────────────────────────────────────────────────────────────────┐
│  📊 PricePulse Analytics                              🔄 Jun 13, 2026  │
├──────────┬──────────┬──────────┬──────────────────────────────────────────┤
│ 105      │ $8,542   │ 34       │ Hace 2h                                │
│ Productos│ Precio   │ Con      │ Última                                  │
│ monitoreados│ promedio│ descuento│ actualización                          │
├──────────┴──────────┴──────────┴──────────────────────────────────────────┤
│  📈 Precios por Categoría          │  📊 Volatilidad por Categoría       │
│  [Bar chart - 7 categorías]        │  [Horizontal bar - volatilidad]     │
│                                    │                                     │
├────────────────────────────────────┴─────────────────────────────────────┤
│  🔥 Top 10 Descuentos                                                   │
│  [Tabla: Producto | Tienda | Precio | Descuento | Cambio]               │
└──────────────────────────────────────────────────────────────────────────┘
```

### Página de Tendencias — Evolución y Patrones

```
┌──────────────────────────────────────────────────────────────────────────┐
│  📈 Tendencias del Mercado                                              │
├──────────────────────────────────────────────────────────────────────────┤
│  📉 Evolución de Precios                                                 │
│  [Line chart multi-producto con selector de categoría]                   │
│                                                                          │
│  📅 Mejor Momento para Comprar     │  📊 Variación por Categoría        │
│  [Día de semana óptimo + avg price]│  [Histograma de cambios %]         │
│                                    │                                     │
│  📦 Distribución de Precios        │  🔄 Cambios Recientes               │
│  [Box plot por categoría]          │  [Tabla de cambios últimos 7 días]  │
└────────────────────────────────────┴─────────────────────────────────────┘
```

### Página de Tiendas — Ranking y Comparativa

```
┌──────────────────────────────────────────────────────────────────────────┐
│  🏪 Tiendas                                                              │
├──────────────────────────────────────────────────────────────────────────┤
│  🏆 Ranking por Precio Promedio     │  🥧 Participación de Mercado      │
│  [Horizontal bar por tienda]        │  [Pie chart por productos]         │
│                                     │                                    │
│  📊 Precio Promedio por Categoría y Tienda                              │
│  [Grouped bar chart - 7 categorías × 3 tiendas]                         │
│                                                                          │
│  📋 Estadísticas Detalladas por Tienda                                  │
│  [Tabla: Tienda | Productos | Precio min/avg/max | Volatilidad]         │
└──────────────────────────────────────────────────────────────────────────┘
```

### Página de Componentes — Detalle por Categoría

```
┌──────────────────────────────────────────────────────────────────────────┐
│  🔧 Componentes                                                          │
├──────────────────────────────────────────────────────────────────────────┤
│  [🖥️ CPUs] [🎮 GPUs] [💾 RAM] [💿 SSD] [💻 Laptops] [🖥️ Mon] [🔧 PM] │
├──────────────────────────────────────────────────────────────────────────┤
│  📋 Productos — CPUs     Filtro: [Marca ▼] [Rango precio ━━━●━━━]      │
│  [Tabla filtrable: Nombre | Marca | Tienda | Precio | Cambio]           │
│                                                                          │
│  📉 Productos Más Volátiles                                              │
│  [Line chart - top 5 productos con mayor volatilidad de precio]         │
│                                                                          │
│  🕐 Mejor Momento para Comprar CPUs: **Martes** (-3.2% vs promedio)     │
│  [Bar chart - precio promedio por día de la semana]                      │
│                                                                          │
│  ▶ AMD Ryzen 7 7800X3D — Mercado Libre                                 │
│    [Precio actual, historial, disponibilidad]                            │
│  ▶ Intel Core i7-14700K — AliExpress                                    │
│    [Precio actual, historial, disponibilidad]                            │
└──────────────────────────────────────────────────────────────────────────┘
```

> 📸 **Nota**: Las capturas anteriores son representaciones textuales del dashboard. Al ejecutar el proyecto se obtiene la experiencia interactiva completa con gráficos Plotly y filtros en tiempo real.

---

## 🧩 Módulos

### `src/config.py` — Configuración Centralizada

Jerarquía de **frozen dataclasses** que carga variables desde `.env` vía `python-dotenv` y las expone como constantes tipadas e inmutables para toda la aplicación.

```
Settings (singleton)
├── DatabaseSettings   → DATABASE_URL, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
├── ScrapeSettings     → delay_min/max, max_retries, retry_delay, products_per_category
├── CurrencySettings   → usd_to_mxn (17.50), base_currency (MXN)
└── AppSettings        → log_level, project_root
```

**Decisión de diseño**: Las frozen dataclasses garantizan inmutabilidad una vez instanciadas — ningún módulo puede modificar la configuración en runtime. El singleton `settings` se importa globalmente (`from src.config import settings`), eliminando la necesidad de pasar configuración por parámetros. La detección automática de dialecto (`is_sqlite`, `is_postgresql`) permite que el resto del código sea agnóstico al motor de BD.

---

### `src/database/` — Capa de Datos Dual

| Archivo | Responsabilidad |
|---|---|
| `models.py` | 5 modelos ORM: Store, Category, Product, PriceHistory, PipelineLog |
| `connection.py` | SessionFactory singleton, `get_session()` context manager, `init_db()`, `check_connection()` |

**Modelo de datos**:

```
stores ←──┐
          │    categories ←──┐
          │                  │
products ─┘──────────────────┘  ←── (name, store_id) UNIQUE
    │
    └──→ price_history  ←── (product_id, scraped_at) UNIQUE

pipeline_logs  (independiente, logging de ejecuciones)
```

**Decisión de diseño — Dual dialect**: La `SessionFactory` configura automáticamente los parámetros óptimos según el dialecto detectado. SQLite usa WAL mode (lecturas concurrentes sin bloquear escrituras), foreign keys explícitas (SQLite las desactiva por defecto), y busy_timeout de 5 segundos. PostgreSQL usa pool_pre_ping (detecta conexiones muertas antes de usarlas), pool_size=5 y max_overflow=10 para concurrencia. Esta abstracción permite desarrollar con SQLite (cero configuración) y desplegar en PostgreSQL (producción) sin cambiar una línea de código de negocio.

**Decisión de diseño — UNIQUE constraints**: Las restricciones `UNIQUE(name, store_id)` en products y `UNIQUE(product_id, scraped_at)` en price_history permiten upserts idempotentes. El pipeline puede ejecutarse múltiples veces sin crear duplicados — fundamental para un sistema de scraping que corre periódicamente.

---

### `src/scrapers/` — Extracción Adaptativa

| Archivo | Estrategia | Anti-scraping |
|---|---|---|
| `mercadolibre_scraper.py` | `requests` + BeautifulSoup | Rate limiting + UA rotation |
| `aliexpress_scraper.py` | Playwright headless | Baxia CAPTCHA detection |
| `temu_scraper.py` | Playwright stealth | Cloudflare bypass + fingerprint masking |

**Decisión de diseño — Strategy Pattern**: Cada tienda tiene requerimientos de scraping radicalmente distintos. Mercado Libre renderiza server-side (suficiente con requests + BS4, más rápido y ligero). AliExpress requiere JS rendering (Playwright). Temu tiene protección anti-bot agresiva (Playwright stealth con fingerprint masking). El abstract base class `BaseScraper` define la interfaz común (`get_products()`, `get_price()`) mientras cada implementación encapsula su lógica específica. Si una tienda cambia su estructura, solo se modifica su scraper — los demás no se ven afectados.

**Decisión de diseño — Cross-cutting en BaseScraper**: El precio se parsea con `_parse_price()` que maneja formatos "$12,345.67" (latino), "$12.345,67" (europeo) y múltiples símbolos de moneda. Los User-Agents rotan de un pool de 8 (Chrome/Firefox/Edge/Safari en Win/Mac). Las estadísticas de scraping se rastrean por instancia (products_found, products_saved, captcha_detected).

---

### `src/transformers/` — Limpieza y Cálculos

| Archivo | Responsabilidad |
|---|---|
| `cleaner.py` | Pipeline de 7 pasos con Pandas para normalización y validación |
| `calculator.py` | Cálculo de price_change y price_change_pct (3 modos) |

**DataCleaner — 7 pasos secuenciales**:

```
1. normalize_names()     → strip, collapse whitespace, remove control chars, capitalize
2. map_categories()      → category name → category_id (via BD lookup)
3. map_stores()          → store name → store_id (via BD lookup)
4. convert_currencies()  → USD → MXN at configurable rate (17.50 default)
5. remove_duplicates()   → dedup by (name, store_id)
6. validate_prices()     → filter out-of-range per category (PriceValidation.RANGES)
7. clean_all()           → execute entire pipeline
```

**Decisión de diseño — Pandas**: Se eligió Pandas sobre operaciones row-by-row por tres razones: (1) vectorización — las operaciones sobre columnas enteras son órdenes de magnitud más rápidas; (2) manejo nativo de NaN — los datos de scraping son inherentemente sucios y Pandas gestiona valores faltantes sin código defensivo; (3) conversión directa — `df.to_dict('records')` produce exactamente el formato que SQLAlchemy necesita para instanciar modelos ORM. Si el volumen crece, la arquitectura permite migrar a PySpark o Dask sin cambiar la interfaz.

**Decisión de diseño — Pre-cómputo de cambios de precio**: Los campos `price_change` y `price_change_pct` se calculan en el pipeline y se almacenan en BD como datos inmutables, en lugar de calcularse on-the-fly con window functions. Esto tiene tres ventajas: (1) las consultas del dashboard son O(1) — no necesitan JOINs ni subconsultas; (2) los datos históricos son inmutables — el precio de ayer no cambia si scrapeamos hoy; (3) la lógica de cálculo está centralizada en `PriceCalculator`, no dispersa en 15 consultas SQL.

---

### `src/pipeline/` — Orquestación ETL

| Archivo | Responsabilidad |
|---|---|
| `etl.py` | PricePulsePipeline — Extract → Transform → Load con resiliencia |

**Flujo de ejecución**:

```
PricePulsePipeline.run()
    │
    ├── Mercado Libre (7 categorías, sequential)
    │   ├── Extract → ScrapeResult[]
    │   ├── Transform → DataCleaner.clean_all() → PriceCalculator
    │   └── Load → Upsert products + Insert price_history
    │
    ├── AliExpress (7 categorías, sequential)
    │   ├── Extract → ScrapeResult[]
    │   ├── Transform → DataCleaner.clean_all() → PriceCalculator
    │   └── Load → Upsert products + Insert price_history
    │
    ├── Temu (7 categorías, sequential)
    │   ├── Extract → ScrapeResult[]
    │   ├── Transform → DataCleaner.clean_all() → PriceCalculator
    │   └── Load → Upsert products + Insert price_history
    │
    └── PipelineLog → status, timing, counts
```

**Decisión de diseño — Resiliencia por niveles**: El pipeline implementa tolerancia a fallos en tres niveles: (1) si un scraper falla completamente, los demás continúan → estado `partial_success`; (2) si una categoría falla dentro de un scraper, se salta y continúa con la siguiente; (3) si todo falla → estado `failure`. El `PipelineLog` registra cada ejecución con métricas detalladas (products_found, products_saved, products_failed, execution_time_ms), permitiendo monitoreo y debugging sin acceder a los contenedores.

---

### `src/analytics/` — Consultas de Negocio

| Archivo | Responsabilidad |
|---|---|
| `queries.py` | AnalyticsService — 15 métodos que retornan DataFrames |

| # | Método | Uso en Dashboard |
|---|---|---|
| 1 | `get_kpi_summary()` | Inicio — KPIs generales |
| 2 | `get_price_evolution(product_id, days)` | Tendencias/Componentes — gráfico de líneas |
| 3 | `get_store_ranking(category_id)` | Tiendas — ranking por precio |
| 4 | `get_category_volatility(days)` | Inicio/Tendencias — barras de volatilidad |
| 5 | `get_top_discounts(n, days)` | Inicio — tabla top descuentos |
| 6 | `get_best_time_to_buy(days)` | Tendencias/Componentes — día óptimo |
| 7 | `get_price_comparison(product_name)` | Comparativa cross-store |
| 8 | `get_category_summary()` | Inicio — resumen por categoría |
| 9 | `get_price_changes(days, category_id)` | Tendencias — cambios recientes |
| 10 | `get_products_list(category_id, store_id)` | Componentes — tabla filtrable |
| 11 | `get_category_price_stats(days)` | Tendencias — box plot |
| 12 | `get_store_category_comparison()` | Tiendas — barras agrupadas |
| 13 | `get_store_detailed_stats()` | Tiendas — tabla detallada |
| 14 | `get_most_volatile_products(category_id, top_n)` | Componentes — top volátiles |
| 15 | `get_product_detail(product_id, days)` | Componentes — expander detalle |

**Decisión de diseño — SQL cross-dialect**: SQLite y PostgreSQL tienen funciones diferentes para operaciones comunes. Por ejemplo, extraer el día de la semana: SQLite usa `strftime('%w', columna)`, PostgreSQL usa `EXTRACT(ISODOW FROM columna)`. El helper `_dialect_extract_dow()` abstrae esta diferencia, detectando el dialecto activo y generando el SQL correcto. Lo mismo aplica para `_dialect_stddev()` (SQLite no tiene `STDDEV()` nativo — se calcula manualmente con `AVG(x*x) - AVG(x)*AVG(x)`). Esto permite que las 15 consultas funcionen idénticamente en ambos motores sin duplicar código.

---

### `src/dashboard/` — Presentación Interactiva

| Archivo | Líneas | Responsabilidad |
|---|---|---|
| `app.py` | 2891 | Dashboard principal con 4 páginas, sidebar, CSS custom |
| `demo_app.py` | 840 | Dashboard standalone SQLite (sin PostgreSQL) |

**4 páginas del dashboard**:

| Página | Contenido | Consultas utilizadas |
|---|---|---|
| 🏠 **Inicio** | 4 KPIs, precios por categoría, volatilidad, top descuentos | 1, 4, 5, 8 |
| 📈 **Tendencias** | Evolución temporal, mejor momento, variación, box plots | 2, 4, 6, 9, 11 |
| 🏪 **Tiendas** | Ranking, comparativa por categoría, market share, stats | 3, 12, 13 |
| 🔧 **Componentes** | 7 tabs por categoría, tabla filtrable, volátiles, mejor hora | 6, 10, 14, 15 |

**Decisión de diseño — st.cache_data(ttl=300)**: Los data loaders usan `@st.cache_data(ttl=300)` para cachear resultados durante 5 minutos. Esto reduce la carga en la BD cuando múltiples usuarios interactúan con el dashboard simultáneamente. El TTL de 300s equilibra frescura de datos (los precios cambian diariamente, no por segundo) con rendimiento. Cada filtro o interacción del usuario que cambia los parámetros de consulta genera un cache miss y ejecuta la consulta fresh.

**Decisión de diseño — Navegación por sidebar**: Se eligió `st.radio` en sidebar sobre `st.tabs` o `st.sidebar.navigation` por tres razones: (1) la navegación está siempre visible independientemente de la posición del scroll; (2) el sidebar también contiene controles globales (ejecutar pipeline, info del sistema) que persisten entre páginas; (3) es compatible con Streamlit Community Cloud sin configuración adicional.

---

## 🛠️ Tecnologías y Justificación

| Tecnología | Versión | Justificación |
|---|---|---|
| **Python** | 3.12+ | Ecosistema maduro para datos (Pandas, SQLAlchemy), scraping (BS4, Playwright) y dashboards (Streamlit). Tipado mejorado con generics nativos en 3.12. |
| **SQLAlchemy** | 2.0+ | ORM maduro con soporte multi-dialect. Permite escribir modelos una vez y ejecutar en SQLite o PostgreSQL sin cambios. Sesiones con context manager garantizan commit/rollback automático. |
| **Pandas** | 2.2+ | Vectorización para transformación de datos. `drop_duplicates()`, `groupby().diff()`, y `to_dict('records')` cubren el 100% de las necesidades del pipeline. |
| **Streamlit** | 1.37+ | Prototipado → producción en minutos. Widgets interactivos sin JavaScript. `st.cache_data` resuelve el rendimiento. Despliegue gratuito en Streamlit Community Cloud. |
| **Plotly** | 5.22+ | Gráficos interactivos (zoom, hover, pan) que Chart.js o Matplotlib no ofrecen nativamente en Streamlit. `go.Scatter`, `go.Bar`, `go.Pie` cubren todas las visualizaciones. |
| **PostgreSQL** | 16 | Producción: `pool_pre_ping`, concurrencia real, `STDDEV()` nativo, `EXTRACT(ISODOW)`, índices parciales. Alpine image = ~80MB en Docker. |
| **SQLite** | Incluido | Desarrollo: cero configuración, un archivo, perfecto para prototipado y Streamlit Cloud. WAL mode permite lecturas concurrentes. |
| **Playwright** | v1.x | Único navegador headless que maneja JS rendering (AliExpress) y stealth mode (Temu). Selenium no tiene fingerprint masking nativo. |
| **BeautifulSoup** | 4.12+ | Parsing HTML server-side (Mercado Libre). Más ligero que Playwright cuando no se necesita JS. Combinado con `requests` = scraping rápido. |
| **Docker** | Compose v2 | Entorno reproducible. `docker compose up` levanta PostgreSQL + Streamlit. Healthchecks garantizan orden de arranque. Volúmenes persistentes. |
| **loguru** | 0.7+ | Logging estructurado con colores, rotación automática y formato consistente. Reemplaza la stdlib `logging` con API más simple (`logger.info()` en vez de configurar handlers). |
| **python-dotenv** | 1.0+ | Carga `.env` automáticamente. Mantiene secrets fuera del código. Compatible con Docker (env vars inyectadas) y Streamlit Cloud (secrets UI). |

---

## 📁 Estructura del Proyecto

```
pricepulse-analytics/
├── .env.example              # Template de variables de entorno
├── .env.docker               # Variables para Docker Compose
├── .streamlit/
│   └── config.toml           # Configuración del servidor Streamlit
├── docker-compose.yml        # PostgreSQL 16 + Streamlit app
├── requirements.txt          # Dependencias Python principales
├── requirements-pg.txt       # psycopg2-binary (solo PostgreSQL)
├── packages.txt              # Paquetes sistema (Playwright deps)
│
├── docker/
│   ├── Dockerfile            # Multi-stage build (python:3.12-slim)
│   ├── entrypoint.sh         # Wait DB → init_db → seed → streamlit
│   └── .dockerignore         # Exclusiones para imagen Docker
│
├── sql/
│   └── create_tables.sql     # DDL PostgreSQL (referencia, no usado por init_db)
│
├── scripts/
│   ├── seed_data.py          # Datos semilla vía SQLAlchemy (PG + SQLite)
│   └── setup_demo.py         # Demo standalone con SQLite3 puro
│
├── src/
│   ├── config.py             # Settings: frozen dataclasses + .env
│   │
│   ├── database/
│   │   ├── models.py         # 5 modelos ORM (Store, Category, Product, PriceHistory, PipelineLog)
│   │   └── connection.py     # SessionFactory, get_session(), init_db(), check_connection()
│   │
│   ├── scrapers/
│   │   ├── base_scraper.py   # ABC + ScrapeResult + UA rotation + price parsing
│   │   ├── scraper_config.py # StoreConfig + StoreSelectors (3 tiendas)
│   │   ├── mercadolibre_scraper.py  # requests + BS4
│   │   ├── aliexpress_scraper.py    # Playwright headless
│   │   └── temu_scraper.py         # Playwright stealth
│   │
│   ├── transformers/
│   │   ├── cleaner.py        # DataCleaner: 7-step Pandas pipeline
│   │   └── calculator.py    # PriceCalculator: 3 modos de cálculo
│   │
│   ├── pipeline/
│   │   └── etl.py            # PricePulsePipeline: Extract→Transform→Load
│   │
│   ├── analytics/
│   │   └── queries.py        # AnalyticsService: 15 consultas → DataFrames
│   │
│   └── dashboard/
│       ├── app.py            # Dashboard principal (4 páginas, 2891 líneas)
│       └── demo_app.py       # Dashboard demo standalone (SQLite)
│
└── docs/
    └── favicon.png           # Logo del proyecto
```

---

## 🐳 Docker

### Levantar con Docker Compose

```bash
# Clonar y configurar
git clone https://github.com/omar11011/pricepulse-analytics.git
cd pricepulse-analytics
cp .env.docker .env

# Levantar todo (PostgreSQL + Streamlit)
docker compose up

# En background
docker compose up -d

# Ver logs
docker compose logs -f app

# Detener
docker compose down

# Reiniciar con datos limpios (elimina volúmenes)
docker compose down -v
docker compose up
```

### Arquitectura Docker

```
┌─────────────────────────────────────────────────┐
│              Docker Compose Network              │
│              (pricepulse-network)                │
│                                                  │
│  ┌────────────────┐     ┌───────────────────┐   │
│  │  pricepulse-db │     │  pricepulse-app   │   │
│  │  postgres:16   │     │  python:3.12-slim │   │
│  │                │     │                   │   │
│  │  Port: 5432    │◄────│  depends_on:      │   │
│  │  Volume: pgdata│     │  service_healthy  │   │
│  │  Healthcheck:  │     │                   │   │
│  │  pg_isready    │     │  Port: 8501       │   │
│  └────────────────┘     │  Entrypoint:      │   │
│                          │  1. Wait PG       │   │
│                          │  2. init_db()     │   │
│                          │  3. seed_data.py  │   │
│                          │  4. streamlit run │   │
│                          └───────────────────┘   │
│                                                  │
│  Volumes: pgdata (PG data), app-data (SQLite)   │
└─────────────────────────────────────────────────┘
```

### Variables de entorno para Docker

| Variable | Default | Descripción |
|---|---|---|
| `DB_NAME` | pricepulse | Nombre de la base de datos |
| `DB_USER` | pricepulse_user | Usuario PostgreSQL |
| `DB_PASSWORD` | pricepulse_secret | Contraseña PostgreSQL |
| `DB_PORT_PUBLISHED` | 5432 | Puerto PG expuesto al host |
| `APP_PORT_PUBLISHED` | 8501 | Puerto Streamlit expuesto |
| `SEED_DATA` | true | Ejecutar datos semilla al iniciar |
| `MAX_WAIT_SECONDS` | 60 | Timeout para esperar PostgreSQL |
| `LOG_LEVEL` | INFO | Nivel de logging |

---

## ⚙️ Configuración

### Variables de Entorno

Crear un archivo `.env` en la raíz del proyecto (ver `.env.example`):

```bash
# SQLite (default — desarrollo local)
DATABASE_URL=sqlite:///data/pricepulse.db

# PostgreSQL (producción con Docker)
# DATABASE_URL=postgresql+psycopg2://pricepulse_user:pricepulse_secret@localhost:5432/pricepulse

# Scraping
SCRAPE_DELAY_MIN=2
SCRAPE_DELAY_MAX=8
SCRAPE_MAX_RETRIES=3

# Moneda
USD_TO_MXN_RATE=17.50

# Logging
LOG_LEVEL=INFO
```

### Detección Automática de Base de Datos

El sistema detecta automáticamente el motor de BD según `DATABASE_URL`:

| DATABASE_URL | Motor | Configuración automática |
|---|---|---|
| `sqlite:///...` | SQLite | WAL mode, FK ON, busy_timeout=5s |
| `postgresql+psycopg2://...` | PostgreSQL | pool_pre_ping, pool_size=5 |
| *(vacío)* | PostgreSQL | Construye URL desde `DB_HOST`, `DB_PORT`, etc. |

### Ejecutar el Pipeline de Scraping

El pipeline se puede ejecutar desde el dashboard (botón ▶ en sidebar) o por línea de comandos:

```bash
# Con SQLite
python -m src.pipeline.etl

# Con PostgreSQL
DATABASE_URL="postgresql+psycopg2://user:pass@localhost:5432/pricepulse" python -m src.pipeline.etl
```

---

## 📋 Requisitos

| Requisito | Versión |
|---|---|
| Python | 3.12+ |
| Docker | 20.10+ (opcional) |
| Docker Compose | v2+ (opcional) |

### Dependencias Python

```
pandas>=2.2.0          # Transformación de datos vectorizada
numpy>=1.26.0          # Cálculos numéricos
sqlalchemy>=2.0.0      # ORM multi-dialect
streamlit>=1.37.0      # Dashboard interactivo
plotly>=5.22.0         # Gráficos interactivos
requests>=2.32.0       # HTTP client (Mercado Libre)
beautifulsoup4>=4.12.0 # HTML parser
python-dotenv>=1.0.1   # Carga .env
loguru>=0.7.2          # Logging estructurado
psycopg2-binary>=2.9.9 # PostgreSQL adapter (solo producción)
```

---

<div align="center">

**PricePulse Analytics** — Monitoreo inteligente de precios tecnológicos para el mercado mexicano.

Hecho con ❤️ por [omar11011](https://github.com/omar11011)

</div>
