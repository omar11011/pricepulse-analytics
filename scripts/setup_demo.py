#!/usr/bin/env python3
"""
PricePulse Analytics — Demo con SQLite.

Prepara una base de datos SQLite temporal con los datos semilla para
que el dashboard funcione sin necesidad de PostgreSQL.

Uso:
    python scripts/setup_demo.py
"""

import sys
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Asegurar path del proyecto
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.seed_data import (
    SEED_STORES, SEED_CATEGORIES, SEED_PRODUCTS,
    STORE_PRICE_MULTIPLIERS, _generate_price_series, _generate_scraped_dates,
)
from src.config import PriceValidation

RANDOM_SEED = 42
random.seed(RANDOM_SEED)

DB_PATH = _PROJECT_ROOT / "demo_pricepulse.db"


def create_tables(cursor: sqlite3.Cursor) -> None:
    """Crea las tablas en SQLite (equivalente a los modelos ORM)."""
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS stores (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            country     TEXT NOT NULL DEFAULT 'México',
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS categories (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            name    TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS products (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL,
            brand        TEXT,
            url          TEXT,
            sku          TEXT,
            category_id  INTEGER NOT NULL REFERENCES categories(id),
            store_id     INTEGER NOT NULL REFERENCES stores(id),
            created_at   TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(name, store_id)
        );

        CREATE TABLE IF NOT EXISTS price_history (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id       INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            price            REAL NOT NULL,
            currency         TEXT NOT NULL DEFAULT 'MXN',
            availability     INTEGER NOT NULL DEFAULT 1,
            price_change     REAL,
            price_change_pct REAL,
            scraped_at       TEXT NOT NULL,
            UNIQUE(product_id, scraped_at)
        );

        CREATE TABLE IF NOT EXISTS pipeline_logs (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            process_name       TEXT NOT NULL,
            status             TEXT NOT NULL,
            message            TEXT,
            execution_time_ms  INTEGER,
            products_found     INTEGER,
            products_saved     INTEGER,
            products_failed    INTEGER,
            created_at         TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- Índices
        CREATE INDEX IF NOT EXISTS ix_products_category_id ON products(category_id);
        CREATE INDEX IF NOT EXISTS ix_products_store_id ON products(store_id);
        CREATE INDEX IF NOT EXISTS ix_price_history_product_id ON price_history(product_id);
        CREATE INDEX IF NOT EXISTS ix_price_history_scraped_at ON price_history(scraped_at);
        CREATE INDEX IF NOT EXISTS ix_pipeline_logs_status ON pipeline_logs(status);
    """)


def seed_data(cursor: sqlite3.Cursor) -> dict[str, int]:
    """Inserta los datos semilla en SQLite."""
    metrics = {"stores": 0, "categories": 0, "products": 0, "prices": 0}

    # Tiendas
    store_ids = {}
    for store in SEED_STORES:
        cursor.execute(
            "INSERT OR IGNORE INTO stores (name, country) VALUES (?, ?)",
            (store["name"], store["country"]),
        )
        cursor.execute("SELECT id FROM stores WHERE name = ?", (store["name"],))
        store_ids[store["name"]] = cursor.fetchone()[0]
        metrics["stores"] += 1

    # Categorías
    category_ids = {}
    for cat_name in SEED_CATEGORIES:
        cursor.execute(
            "INSERT OR IGNORE INTO categories (name) VALUES (?)",
            (cat_name,),
        )
        cursor.execute("SELECT id FROM categories WHERE name = ?", (cat_name,))
        category_ids[cat_name] = cursor.fetchone()[0]
        metrics["categories"] += 1

    # Productos y precios
    trends = ["up", "down", "stable", "mixed"]
    now = datetime.now(timezone.utc)

    for product_def in SEED_PRODUCTS:
        category_id = category_ids[product_def["category"]]
        product_trend = random.choice(trends)
        num_price_records = random.randint(3, 5)

        for store_name, store_id in store_ids.items():
            # URL y SKU por tienda
            if store_name == "Mercado Libre":
                url = product_def.get("url_ml")
                sku = product_def.get("sku_ml")
            elif store_name == "AliExpress":
                url = product_def.get("url_ae")
                sku = product_def.get("sku_ae")
            else:
                url = product_def.get("url_temu", product_def.get("url_ae"))
                sku = product_def.get("sku_temu", product_def.get("sku_ae"))

            # Upsert producto
            cursor.execute(
                "SELECT id FROM products WHERE name = ? AND store_id = ?",
                (product_def["name"], store_id),
            )
            row = cursor.fetchone()

            if row:
                product_id = row[0]
                cursor.execute(
                    "UPDATE products SET brand=?, url=?, sku=?, category_id=? WHERE id=?",
                    (product_def["brand"], url, sku, category_id, product_id),
                )
            else:
                cursor.execute(
                    "INSERT INTO products (name, brand, url, sku, category_id, store_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (product_def["name"], product_def["brand"], url, sku, category_id, store_id),
                )
                product_id = cursor.lastrowid

            metrics["products"] += 1

            # Generar precios
            price_series = _generate_price_series(
                base_price=product_def["base_price_mx"],
                num_records=num_price_records,
                store_name=store_name,
                trend=product_trend,
            )
            scraped_dates = _generate_scraped_dates(num_records=num_price_records, days_back=30)

            for idx, (price, scraped_at) in enumerate(zip(price_series, scraped_dates)):
                # Validar precio
                if not PriceValidation.is_valid_price(product_def["category"], price):
                    min_p, max_p = PriceValidation.RANGES[product_def["category"]]
                    price = max(min_p, min(max_p, price))

                # Calcular variaciones
                if idx == 0:
                    cursor.execute(
                        "SELECT price FROM price_history WHERE product_id = ? AND scraped_at < ? ORDER BY scraped_at DESC LIMIT 1",
                        (product_id, scraped_at.isoformat()),
                    )
                    last_row = cursor.fetchone()
                    if last_row and last_row[0] > 0:
                        prev_price = last_row[0]
                        price_change = round(price - prev_price, 2)
                        price_change_pct = round(((price - prev_price) / prev_price) * 100, 2)
                    else:
                        price_change = None
                        price_change_pct = None
                else:
                    prev_price = price_series[idx - 1]
                    price_change = round(price - prev_price, 2)
                    price_change_pct = round(((price - prev_price) / prev_price) * 100, 2) if prev_price > 0 else None

                # Deduplicar
                day_start = scraped_at.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
                day_end = scraped_at.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()

                cursor.execute(
                    "SELECT id FROM price_history WHERE product_id = ? AND scraped_at >= ? AND scraped_at <= ?",
                    (product_id, day_start, day_end),
                )
                if not cursor.fetchone():
                    cursor.execute(
                        "INSERT INTO price_history (product_id, price, currency, availability, price_change, price_change_pct, scraped_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (product_id, price, "MXN", 1, price_change, price_change_pct, scraped_at.isoformat()),
                    )
                    metrics["prices"] += 1

    # Log de pipeline demo
    cursor.execute(
        "INSERT INTO pipeline_logs (process_name, status, message, execution_time_ms, products_found, products_saved, products_failed) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("demo_seed", "success", "Datos semilla cargados para demo", 0, metrics["products"], metrics["products"], 0),
    )

    return metrics


def main() -> None:
    """Ejecuta la configuración del demo."""
    # Eliminar BD anterior si existe
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"BD anterior eliminada: {DB_PATH}")

    # Crear nueva BD
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    print("Creando tablas...")
    create_tables(cursor)

    print("Insertando datos semilla...")
    metrics = seed_data(cursor)

    conn.commit()
    conn.close()

    print(f"\n✅ Demo listo!")
    print(f"   BD: {DB_PATH}")
    print(f"   Tiendas: {metrics['stores']}")
    print(f"   Categorías: {metrics['categories']}")
    print(f"   Productos: {metrics['products']}")
    print(f"   Registros de precio: {metrics['prices']}")
    print(f"\n   Ejecuta: streamlit run src/dashboard/demo_app.py")


if __name__ == "__main__":
    main()
