-- ============================================================
-- PricePulse Analytics — DDL Script
-- PostgreSQL 15+
--
-- Ejecutar con:
--   psql -U pricepulse_user -d pricepulse -f create_tables.sql
--
-- O dentro de Docker:
--   docker exec -i pricepulse-db psql -U pricepulse_user -d pricepulse < create_tables.sql
-- ============================================================

-- Limpieza previa (solo para desarrollo — NO usar en producción)
-- DROP TABLE IF EXISTS pipeline_logs, price_history, products, categories, stores CASCADE;

-- ============================================================
-- TABLA: stores
-- Tiendas online monitoreadas por el sistema
-- ============================================================
CREATE TABLE IF NOT EXISTS stores (
    id          SERIAL          PRIMARY KEY,
    name        VARCHAR(100)    NOT NULL UNIQUE,
    country     VARCHAR(50)     NOT NULL DEFAULT 'México',
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- ============================================================
-- TABLA: categories
-- Categorías de productos tecnológicos
-- ============================================================
CREATE TABLE IF NOT EXISTS categories (
    id      SERIAL          PRIMARY KEY,
    name    VARCHAR(50)     NOT NULL UNIQUE
);

-- ============================================================
-- TABLA: products
-- Productos detectados en cada tienda
-- Restricción UNIQUE(name, store_id) para upsert idempotente
-- ============================================================
CREATE TABLE IF NOT EXISTS products (
    id           SERIAL          PRIMARY KEY,
    name         VARCHAR(300)    NOT NULL,
    brand        VARCHAR(100),
    url          TEXT,
    sku          VARCHAR(100),
    category_id  INTEGER         NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
    store_id     INTEGER         NOT NULL REFERENCES stores(id) ON DELETE RESTRICT,
    created_at   TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_product_name_store UNIQUE (name, store_id)
);

-- Índices para consultas frecuentes del dashboard
CREATE INDEX IF NOT EXISTS ix_products_category_id  ON products(category_id);
CREATE INDEX IF NOT EXISTS ix_products_store_id     ON products(store_id);
CREATE INDEX IF NOT EXISTS ix_products_brand        ON products(brand);

-- ============================================================
-- TABLA: price_history
-- Historial de precios por producto y fecha
-- Un registro por producto por día (deduplicación)
-- ============================================================
CREATE TABLE IF NOT EXISTS price_history (
    id               SERIAL          PRIMARY KEY,
    product_id       INTEGER         NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    price            DOUBLE PRECISION NOT NULL,
    currency         VARCHAR(10)     NOT NULL DEFAULT 'MXN',
    availability     BOOLEAN         NOT NULL DEFAULT TRUE,
    price_change     DOUBLE PRECISION,
    price_change_pct DOUBLE PRECISION,
    scraped_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_price_product_date UNIQUE (product_id, scraped_at)
);

-- Índices para series temporales y analytics
CREATE INDEX IF NOT EXISTS ix_price_history_product_id   ON price_history(product_id);
CREATE INDEX IF NOT EXISTS ix_price_history_scraped_at   ON price_history(scraped_at);
CREATE INDEX IF NOT EXISTS ix_price_history_product_date ON price_history(product_id, scraped_at);
CREATE INDEX IF NOT EXISTS ix_price_history_currency     ON price_history(currency);

-- ============================================================
-- TABLA: pipeline_logs
-- Registro de ejecuciones del pipeline ETL
-- ============================================================
CREATE TABLE IF NOT EXISTS pipeline_logs (
    id                 SERIAL      PRIMARY KEY,
    process_name       VARCHAR(100) NOT NULL,
    status             VARCHAR(20)  NOT NULL,
    message            TEXT,
    execution_time_ms  INTEGER,
    products_found     INTEGER,
    products_saved     INTEGER,
    products_failed    INTEGER,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Índices para monitoreo del pipeline
CREATE INDEX IF NOT EXISTS ix_pipeline_logs_created_at   ON pipeline_logs(created_at);
CREATE INDEX IF NOT EXISTS ix_pipeline_logs_status       ON pipeline_logs(status);
CREATE INDEX IF NOT EXISTS ix_pipeline_logs_process_name ON pipeline_logs(process_name);

-- ============================================================
-- DATOS INICIALES — Categorías
-- Se insertan solo si no existen (idempotente)
-- ============================================================
INSERT INTO categories (name) VALUES ('CPUs')
    ON CONFLICT (name) DO NOTHING;
INSERT INTO categories (name) VALUES ('GPUs')
    ON CONFLICT (name) DO NOTHING;
INSERT INTO categories (name) VALUES ('RAM')
    ON CONFLICT (name) DO NOTHING;
INSERT INTO categories (name) VALUES ('SSD')
    ON CONFLICT (name) DO NOTHING;
INSERT INTO categories (name) VALUES ('Laptops')
    ON CONFLICT (name) DO NOTHING;
INSERT INTO categories (name) VALUES ('Monitores')
    ON CONFLICT (name) DO NOTHING;
INSERT INTO categories (name) VALUES ('Placas madre')
    ON CONFLICT (name) DO NOTHING;

-- ============================================================
-- DATOS INICIALES — Tiendas
-- Se insertan solo si no existen (idempotente)
-- ============================================================
INSERT INTO stores (name, country) VALUES ('Mercado Libre', 'México')
    ON CONFLICT (name) DO NOTHING;
INSERT INTO stores (name, country) VALUES ('AliExpress', 'China')
    ON CONFLICT (name) DO NOTHING;
INSERT INTO stores (name, country) VALUES ('Temu', 'China')
    ON CONFLICT (name) DO NOTHING;

-- ============================================================
-- COMENTARIOS EN TABLAS (documentación en BD)
-- ============================================================
COMMENT ON TABLE stores         IS 'Tiendas online monitoreadas por PricePulse';
COMMENT ON TABLE categories     IS 'Categorías de productos tecnológicos';
COMMENT ON TABLE products       IS 'Productos detectados; UNIQUE(name, store_id) para upsert';
COMMENT ON TABLE price_history  IS 'Historial de precios; UNIQUE(product_id, scraped_at) para deduplicación diaria';
COMMENT ON TABLE pipeline_logs  IS 'Registro de ejecuciones del pipeline ETL';
