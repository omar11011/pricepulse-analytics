#!/usr/bin/env python3
"""
PricePulse Analytics — Script de Datos Semilla.

Puebla la base de datos con datos realistas del mercado mexicano de tecnología
para que el dashboard funcione desde el primer momento, incluso si el scraping
falla o no se ha ejecutado aún.

Datos insertados:
    - 3 tiendas:  Mercado Libre, AliExpress, Temu
    - 7 categorías: CPUs, GPUs, RAM, SSD, Laptops, Monitores, Placas madre
    - 105 productos (5 por categoría × 3 tiendas) con nombres, marcas y URLs
    - 3-5 registros de precio histórico por producto (simulando 30 días)
      con variaciones realistas que permitan visualizar tendencias

Idempotencia:
    - Tiendas y categorías: INSERT ... ON CONFLICT DO NOTHING
    - Productos: upsert por (name, store_id) — si ya existe, se actualiza
    - Price history: verifica existencia antes de insertar por (product_id, fecha)
    - Se puede ejecutar múltiples veces sin crear duplicados

Ejecución:
    # Desde la raíz del proyecto:
    python -m scripts.seed_data

    # O directamente:
    python scripts/seed_data.py

    # Con variables de entorno personalizadas:
    DB_HOST=localhost DB_PORT=5432 python scripts/seed_data.py

Decisiones de diseño:
    - Precios base definidos para Mercado Libre (referencia del mercado MX)
    - AliExpress típicamente 10-20% más barato (envío directo desde China)
    - Temu típicamente 20-30% más barato (modelo de precios agresivo)
    - Variaciones de precio simuladas con random walk controlado
    - Tendencias mixtas: algunos productos suben, otros bajan, otros estables
    - Los price_change y price_change_pct se calculan correctamente
    - Las fechas de scraped_at se distribuyen en los últimos 30 días
"""

import sys
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import and_
from sqlalchemy.orm import Session

# Asegurar que el directorio del proyecto esté en sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config import Categories, Stores, PriceValidation, settings
from src.database.connection import get_session, init_db, check_connection
from src.database.models import Base, Store, Category, Product, PriceHistory


# ---------------------------------------------------------------------------
# Configuración del generador de aleatoriedad (reproducible)
# ---------------------------------------------------------------------------
RANDOM_SEED = 42
random.seed(RANDOM_SEED)


# ---------------------------------------------------------------------------
# Definición de tiendas
# ---------------------------------------------------------------------------
SEED_STORES: list[dict[str, str]] = [
    {"name": "Mercado Libre", "country": "México"},
    {"name": "AliExpress", "country": "China"},
    {"name": "Temu", "country": "China"},
]


# ---------------------------------------------------------------------------
# Definición de categorías
# ---------------------------------------------------------------------------
SEED_CATEGORIES: list[str] = [
    "CPUs",
    "GPUs",
    "RAM",
    "SSD",
    "Laptops",
    "Monitores",
    "Placas madre",
]


# ---------------------------------------------------------------------------
# Definición de productos — Precios base en MXN (referencia Mercado Libre)
# ---------------------------------------------------------------------------
# Cada producto tiene: name, brand, category, base_price_mx, url_pattern, sku_pattern
# Los precios base son realistas para el mercado mexicano de tecnología en 2024-2025
# AliExpress y Temu aplican multiplicadores de descuento automáticamente

SEED_PRODUCTS: list[dict[str, Any]] = [
    # ── CPUs ──────────────────────────────────────────────────────────
    {
        "name": "AMD Ryzen 5 5600X Procesador Desktop 6 Núcleos",
        "brand": "AMD",
        "category": "CPUs",
        "base_price_mx": 4299.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-AMD-Ryzen-5-5600X",
        "url_ae": "https://www.aliexpress.com/item/AMD-Ryzen-5-5600X",
        "sku_ml": "ML-5600X-BX",
        "sku_ae": "AE-1005006298712345",
        "sku_temu": "TEMU-5600X-PROC",
    },
    {
        "name": "AMD Ryzen 7 5800X Procesador 8 Núcleos 16 Hilos",
        "brand": "AMD",
        "category": "CPUs",
        "base_price_mx": 5999.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-AMD-Ryzen-7-5800X",
        "url_ae": "https://www.aliexpress.com/item/AMD-Ryzen-7-5800X",
        "sku_ml": "ML-5800X-BX",
        "sku_ae": "AE-1005006298723456",
        "sku_temu": "TEMU-5800X-PROC",
    },
    {
        "name": "AMD Ryzen 9 7950X Procesador 16 Núcleos AM5",
        "brand": "AMD",
        "category": "CPUs",
        "base_price_mx": 13999.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-AMD-Ryzen-9-7950X",
        "url_ae": "https://www.aliexpress.com/item/AMD-Ryzen-9-7950X",
        "sku_ml": "ML-7950X-BX",
        "sku_ae": "AE-1005006298734567",
        "sku_temu": "TEMU-7950X-PROC",
    },
    {
        "name": "Intel Core i5-13600K Procesador 14 Núcleos LGA1700",
        "brand": "Intel",
        "category": "CPUs",
        "base_price_mx": 6499.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-Intel-i5-13600K",
        "url_ae": "https://www.aliexpress.com/item/Intel-Core-i5-13600K",
        "sku_ml": "ML-I5-13600K-BX",
        "sku_ae": "AE-1005006298745678",
        "sku_temu": "TEMU-I5-13600K-PROC",
    },
    {
        "name": "Intel Core i7-13700K Procesador 16 Núcleos Gen 13",
        "brand": "Intel",
        "category": "CPUs",
        "base_price_mx": 9499.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-Intel-i7-13700K",
        "url_ae": "https://www.aliexpress.com/item/Intel-Core-i7-13700K",
        "sku_ml": "ML-I7-13700K-BX",
        "sku_ae": "AE-1005006298756789",
        "sku_temu": "TEMU-I7-13700K-PROC",
    },

    # ── GPUs ──────────────────────────────────────────────────────────
    {
        "name": "NVIDIA GeForce RTX 4060 8GB GDDR6 Tarjeta Gráfica",
        "brand": "NVIDIA",
        "category": "GPUs",
        "base_price_mx": 8999.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-NVIDIA-RTX-4060",
        "url_ae": "https://www.aliexpress.com/item/NVIDIA-RTX-4060-8GB",
        "sku_ml": "ML-RTX4060-8G",
        "sku_ae": "AE-1005006298767890",
        "sku_temu": "TEMU-RTX4060-GPU",
    },
    {
        "name": "NVIDIA GeForce RTX 4070 Super 12GB GDDR6X",
        "brand": "NVIDIA",
        "category": "GPUs",
        "base_price_mx": 15999.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-NVIDIA-RTX-4070S",
        "url_ae": "https://www.aliexpress.com/item/NVIDIA-RTX-4070-Super",
        "sku_ml": "ML-RTX4070S-12G",
        "sku_ae": "AE-1005006298778901",
        "sku_temu": "TEMU-RTX4070S-GPU",
    },
    {
        "name": "NVIDIA GeForce RTX 4090 24GB GDDR6X Tarjeta Gráfica",
        "brand": "NVIDIA",
        "category": "GPUs",
        "base_price_mx": 42999.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-NVIDIA-RTX-4090",
        "url_ae": "https://www.aliexpress.com/item/NVIDIA-RTX-4090-24GB",
        "sku_ml": "ML-RTX4090-24G",
        "sku_ae": "AE-1005006298789012",
        "sku_temu": "TEMU-RTX4090-GPU",
    },
    {
        "name": "AMD Radeon RX 7600 8GB GDDR6 Tarjeta Gráfica",
        "brand": "AMD",
        "category": "GPUs",
        "base_price_mx": 6499.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-AMD-RX-7600",
        "url_ae": "https://www.aliexpress.com/item/AMD-RX-7600-8GB",
        "sku_ml": "ML-RX7600-8G",
        "sku_ae": "AE-1005006298790123",
        "sku_temu": "TEMU-RX7600-GPU",
    },
    {
        "name": "AMD Radeon RX 7900 XTX 24GB GDDR6 Tarjeta Gráfica",
        "brand": "AMD",
        "category": "GPUs",
        "base_price_mx": 24999.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-AMD-RX-7900XTX",
        "url_ae": "https://www.aliexpress.com/item/AMD-RX-7900-XTX",
        "sku_ml": "ML-RX7900XTX-24G",
        "sku_ae": "AE-1005006298801234",
        "sku_temu": "TEMU-RX7900XTX-GPU",
    },

    # ── RAM ───────────────────────────────────────────────────────────
    {
        "name": "Corsair Vengeance DDR5 16GB 5600MHz RAM Desktop",
        "brand": "Corsair",
        "category": "RAM",
        "base_price_mx": 899.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-Corsair-Vengeance-DDR5-16GB",
        "url_ae": "https://www.aliexpress.com/item/Corsair-Vengeance-DDR5-16GB",
        "sku_ml": "ML-CMK16GX5M1B5600",
        "sku_ae": "AE-1005006298812345",
        "sku_temu": "TEMU-CORS-DDR5-16G",
    },
    {
        "name": "G.Skill Trident Z5 RGB DDR5 32GB 6000MHz RAM",
        "brand": "G.Skill",
        "category": "RAM",
        "base_price_mx": 2499.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-GSkill-Trident-Z5-32GB",
        "url_ae": "https://www.aliexpress.com/item/GSkill-Trident-Z5-DDR5-32GB",
        "sku_ml": "ML-F5-6000J3038F32G",
        "sku_ae": "AE-1005006298823456",
        "sku_temu": "TEMU-GSKILL-Z5-32G",
    },
    {
        "name": "Kingston Fury Beast DDR4 16GB 3200MHz RAM Gaming",
        "brand": "Kingston",
        "category": "RAM",
        "base_price_mx": 649.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-Kingston-Fury-DDR4-16GB",
        "url_ae": "https://www.aliexpress.com/item/Kingston-Fury-Beast-DDR4-16GB",
        "sku_ml": "ML-KF432C16BB1-16",
        "sku_ae": "AE-1005006298834567",
        "sku_temu": "TEMU-KNGST-FURY-16G",
    },
    {
        "name": "Corsair Vengeance DDR5 64GB Kit 5600MHz 2x32GB",
        "brand": "Corsair",
        "category": "RAM",
        "base_price_mx": 5499.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-Corsair-Vengeance-64GB-Kit",
        "url_ae": "https://www.aliexpress.com/item/Corsair-Vengeance-DDR5-64GB-Kit",
        "sku_ml": "ML-CMK64GX5M2B5600",
        "sku_ae": "AE-1005006298845678",
        "sku_temu": "TEMU-CORS-DDR5-64G",
    },
    {
        "name": "Kingston FURY Renegade DDR4 32GB 3600MHz RAM",
        "brand": "Kingston",
        "category": "RAM",
        "base_price_mx": 1299.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-Kingston-Fury-Renegade-32GB",
        "url_ae": "https://www.aliexpress.com/item/Kingston-FURY-Renegade-32GB",
        "sku_ml": "ML-KF436C16RB1K2-32",
        "sku_ae": "AE-1005006298856789",
        "sku_temu": "TEMU-KNGST-RENEG-32G",
    },

    # ── SSD ───────────────────────────────────────────────────────────
    {
        "name": "Samsung 980 PRO 1TB SSD NVMe M.2 PCIe 4.0",
        "brand": "Samsung",
        "category": "SSD",
        "base_price_mx": 2299.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-Samsung-980-PRO-1TB",
        "url_ae": "https://www.aliexpress.com/item/Samsung-980-PRO-1TB-NVMe",
        "sku_ml": "ML-MZ-V8P1T0B",
        "sku_ae": "AE-1005006298867890",
        "sku_temu": "TEMU-SMSNG-980P-1T",
    },
    {
        "name": "Western Digital WD Black SN850X 1TB SSD NVMe",
        "brand": "Western Digital",
        "category": "SSD",
        "base_price_mx": 2499.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-WD-Black-SN850X-1TB",
        "url_ae": "https://www.aliexpress.com/item/WD-Black-SN850X-1TB-SSD",
        "sku_ml": "ML-WDS100T1X0E",
        "sku_ae": "AE-1005006298878901",
        "sku_temu": "TEMU-WDBLK-SN850X-1T",
    },
    {
        "name": "Kingston NV2 500GB SSD NVMe M.2 PCIe 4.0",
        "brand": "Kingston",
        "category": "SSD",
        "base_price_mx": 549.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-Kingston-NV2-500GB",
        "url_ae": "https://www.aliexpress.com/item/Kingston-NV2-500GB-SSD",
        "sku_ml": "ML-SNV2S-500G",
        "sku_ae": "AE-1005006298889012",
        "sku_temu": "TEMU-KNGST-NV2-500",
    },
    {
        "name": "Samsung 870 EVO 1TB SSD SATA 2.5 Pulgadas",
        "brand": "Samsung",
        "category": "SSD",
        "base_price_mx": 1399.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-Samsung-870-EVO-1TB",
        "url_ae": "https://www.aliexpress.com/item/Samsung-870-EVO-1TB-SATA",
        "sku_ml": "ML-MZ-77E1T0B",
        "sku_ae": "AE-1005006298890123",
        "sku_temu": "TEMU-SMSNG-870E-1T",
    },
    {
        "name": "Crucial P3 Plus 2TB SSD NVMe M.2 PCIe Gen4",
        "brand": "Crucial",
        "category": "SSD",
        "base_price_mx": 2899.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-Crucial-P3-Plus-2TB",
        "url_ae": "https://www.aliexpress.com/item/Crucial-P3-Plus-2TB-SSD",
        "sku_ml": "ML-CT2000P3PSSD8",
        "sku_ae": "AE-1005006298901234",
        "sku_temu": "TEMU-CRUCIAL-P3P-2T",
    },

    # ── Laptops ───────────────────────────────────────────────────────
    {
        "name": "ASUS ROG Strix G16 Gaming Laptop Intel i7 16GB RTX 4060",
        "brand": "ASUS",
        "category": "Laptops",
        "base_price_mx": 29999.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-ASUS-ROG-Strix-G16",
        "url_ae": "https://www.aliexpress.com/item/ASUS-ROG-Strix-G16-Laptop",
        "sku_ml": "ML-G614JI-AS94",
        "sku_ae": "AE-1005006298912345",
        "sku_temu": "TEMU-ASUS-ROG-G16",
    },
    {
        "name": "Lenovo Legion 5 Laptop Gaming AMD Ryzen 7 RTX 4060",
        "brand": "Lenovo",
        "category": "Laptops",
        "base_price_mx": 26999.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-Lenovo-Legion-5",
        "url_ae": "https://www.aliexpress.com/item/Lenovo-Legion-5-Laptop",
        "sku_ml": "ML-82YU000CLM",
        "sku_ae": "AE-1005006298923456",
        "sku_temu": "TEMU-LENVO-LEGION5",
    },
    {
        "name": "Apple MacBook Air M2 13 Pulgadas 8GB 256GB SSD",
        "brand": "Apple",
        "category": "Laptops",
        "base_price_mx": 27999.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-Apple-MacBook-Air-M2",
        "url_ae": "https://www.aliexpress.com/item/Apple-MacBook-Air-M2-13",
        "sku_ml": "ML-MLY33CLA",
        "sku_ae": "AE-1005006298934567",
        "sku_temu": "TEMU-APPL-MBA-M2",
    },
    {
        "name": "HP Victus 15 Laptop Gaming Intel i5 RTX 3050 8GB",
        "brand": "HP",
        "category": "Laptops",
        "base_price_mx": 15999.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-HP-Victus-15",
        "url_ae": "https://www.aliexpress.com/item/HP-Victus-15-Laptop",
        "sku_ml": "ML-FB0051LA",
        "sku_ae": "AE-1005006298945678",
        "sku_temu": "TEMU-HP-VICTUS-15",
    },
    {
        "name": "Dell G15 Gaming Laptop Intel i5 16GB RTX 4050",
        "brand": "Dell",
        "category": "Laptops",
        "base_price_mx": 21499.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-Dell-G15-Gaming",
        "url_ae": "https://www.aliexpress.com/item/Dell-G15-Gaming-Laptop",
        "sku_ml": "ML-G15-5530-9S7",
        "sku_ae": "AE-1005006298956789",
        "sku_temu": "TEMU-DELL-G15-4050",
    },

    # ── Monitores ─────────────────────────────────────────────────────
    {
        "name": "Samsung Odyssey G7 27 Pulgadas QHD 240Hz Curvo Gaming",
        "brand": "Samsung",
        "category": "Monitores",
        "base_price_mx": 9999.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-Samsung-Odyssey-G7-27",
        "url_ae": "https://www.aliexpress.com/item/Samsung-Odyssey-G7-27-Monitor",
        "sku_ml": "ML-LC27G75TQSMX",
        "sku_ae": "AE-1005006298967890",
        "sku_temu": "TEMU-SMSNG-ODYS-G7",
    },
    {
        "name": "LG UltraGear 27GP850-B 27 Pulgadas QHD 165Hz Nano IPS",
        "brand": "LG",
        "category": "Monitores",
        "base_price_mx": 7499.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-LG-UltraGear-27GP850",
        "url_ae": "https://www.aliexpress.com/item/LG-UltraGear-27GP850-Monitor",
        "sku_ml": "ML-27GP850-B",
        "sku_ae": "AE-1005006298978901",
        "sku_temu": "TEMU-LG-ULTGEAR-27",
    },
    {
        "name": "ASUS TUF Gaming VG279QM 27 Pulgadas Full HD 280Hz",
        "brand": "ASUS",
        "category": "Monitores",
        "base_price_mx": 6499.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-ASUS-TUF-VG279QM",
        "url_ae": "https://www.aliexpress.com/item/ASUS-TUF-Gaming-VG279QM",
        "sku_ml": "ML-90LM02K0-B01170",
        "sku_ae": "AE-1005006298989012",
        "sku_temu": "TEMU-ASUS-TUF-27",
    },
    {
        "name": "BenQ MOBIUZ EX2710S 27 Pulgadas Full HD 165Hz IPS Gaming",
        "brand": "BenQ",
        "category": "Monitores",
        "base_price_mx": 7999.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-BenQ-MOBIUZ-EX2710S",
        "url_ae": "https://www.aliexpress.com/item/BenQ-MOBIUZ-EX2710S-27",
        "sku_ml": "ML-EX2710S",
        "sku_ae": "AE-1005006298990123",
        "sku_temu": "TEMU-BENQ-MOB-27",
    },
    {
        "name": "Dell S2722QC 27 Pulgadas 4K UHD USB-C Monitor",
        "brand": "Dell",
        "category": "Monitores",
        "base_price_mx": 10999.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-Dell-S2722QC-4K",
        "url_ae": "https://www.aliexpress.com/item/Dell-S2722QC-4K-Monitor",
        "sku_ml": "ML-DELL-S2722QC",
        "sku_ae": "AE-1005006299001234",
        "sku_temu": "TEMU-DELL-S2722QC",
    },

    # ── Placas madre ──────────────────────────────────────────────────
    {
        "name": "ASUS ROG Strix B550-F Gaming WiFi AM4 Motherboard",
        "brand": "ASUS",
        "category": "Placas madre",
        "base_price_mx": 3699.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-ASUS-ROG-Strix-B550F",
        "url_ae": "https://www.aliexpress.com/item/ASUS-ROG-Strix-B550-F",
        "sku_ml": "ML-ROG-STRIX-B550-F",
        "sku_ae": "AE-1005006299012345",
        "sku_temu": "TEMU-ASUS-B550F-ROG",
    },
    {
        "name": "MSI MAG B660 Tomahawk WiFi DDR4 LGA1700 Motherboard",
        "brand": "MSI",
        "category": "Placas madre",
        "base_price_mx": 2999.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-MSI-MAG-B660-Tomahawk",
        "url_ae": "https://www.aliexpress.com/item/MSI-MAG-B660-Tomahawk-WiFi",
        "sku_ml": "ML-MAG-B660-TOMAHAWK",
        "sku_ae": "AE-1005006299023456",
        "sku_temu": "TEMU-MSI-B660-TOM",
    },
    {
        "name": "Gigabyte B550 AORUS Elite V2 AM4 ATX Motherboard",
        "brand": "Gigabyte",
        "category": "Placas madre",
        "base_price_mx": 3199.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-Gigabyte-B550-AORUS-Elite",
        "url_ae": "https://www.aliexpress.com/item/Gigabyte-B550-AORUS-Elite-V2",
        "sku_ml": "ML-B550-AORUS-ELITE-V2",
        "sku_ae": "AE-1005006299034567",
        "sku_temu": "TEMU-GBTE-B550-AORUS",
    },
    {
        "name": "ASUS TUF Gaming B650-PLUS WiFi AM5 DDR5 Motherboard",
        "brand": "ASUS",
        "category": "Placas madre",
        "base_price_mx": 4999.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-ASUS-TUF-B650-PLUS",
        "url_ae": "https://www.aliexpress.com/item/ASUS-TUF-Gaming-B650-PLUS",
        "sku_ml": "ML-TUF-GAMING-B650-PLUS",
        "sku_ae": "AE-1005006299045678",
        "sku_temu": "TEMU-ASUS-B650-TUF",
    },
    {
        "name": "MSI PRO B760-P WiFi DDR4 LGA1700 ATX Motherboard",
        "brand": "MSI",
        "category": "Placas madre",
        "base_price_mx": 2499.00,
        "url_ml": "https://articulo.mercadolibre.com.mx/MLM-MSI-PRO-B760-P",
        "url_ae": "https://www.aliexpress.com/item/MSI-PRO-B760-P-WiFi",
        "sku_ml": "ML-PRO-B760-P-WIFI",
        "sku_ae": "AE-1005006299056789",
        "sku_temu": "TEMU-MSI-B760-PRO",
    },
]


# ---------------------------------------------------------------------------
# Multiplicadores de precio por tienda
# ---------------------------------------------------------------------------
# Mercado Libre: referencia (precio base del mercado mexicano con IVA e importación)
# AliExpress: 10-20% más barato (envío directo, sin intermediarios locales)
# Temu: 20-30% más barato (modelo de precios agresivo, volumen masivo)
STORE_PRICE_MULTIPLIERS: dict[str, float] = {
    "Mercado Libre": 1.00,
    "AliExpress": 0.85,
    "Temu": 0.75,
}


# ---------------------------------------------------------------------------
# Generación de historial de precios
# ---------------------------------------------------------------------------
def _generate_price_series(
    base_price: float,
    num_records: int,
    store_name: str,
    trend: str = "mixed",
) -> list[float]:
    """Genera una serie de precios con variaciones realistas.

    Simula un random walk controlado con tendencia opcional:
        - "up":    tendencia al alza (oferta agotándose, inflación)
        - "down":  tendencia a la baja (promoción, competencia)
        - "stable": precio casi sin cambios (producto establecido)
        - "mixed": variación aleatoria sin tendencia clara (default)

    Las variaciones diarias son de entre -3% y +3%, realistas para
    e-commerce de tecnología en México. Se añaden "saltos" ocasionales
    para simular promociones o ajustes de precio.

    Args:
        base_price:  Precio base de referencia (MXN)
        num_records: Número de registros de precio a generar
        store_name:  Nombre de la tienda (para ajustar volatilidad)
        trend:       Tendencia de la serie ("up", "down", "stable", "mixed")

    Returns:
        Lista de precios en orden cronológico (del más antiguo al más reciente)
    """
    multiplier = STORE_PRICE_MULTIPLIERS.get(store_name, 1.0)
    current_price = base_price * multiplier

    # Volatilidad por tienda: ML más estable, Temu más volátil
    daily_volatility = {
        "Mercado Libre": 0.015,
        "AliExpress": 0.020,
        "Temu": 0.025,
    }.get(store_name, 0.020)

    # Sesgo de tendencia
    trend_bias = {
        "up": 0.003,
        "down": -0.003,
        "stable": 0.0,
        "mixed": 0.0,
    }.get(trend, 0.0)

    prices: list[float] = []

    for i in range(num_records):
        # Variación diaria normal
        daily_change = random.gauss(trend_bias, daily_volatility)

        # Salto de precio ocasional (promoción o ajuste, ~10% probabilidad)
        if random.random() < 0.10:
            jump = random.uniform(-0.08, 0.05)  # Más bajadas que subidas (promos)
            daily_change += jump

        current_price = current_price * (1 + daily_change)

        # Redondear a 2 decimales (precio real en e-commerce)
        current_price = round(current_price, 2)

        prices.append(current_price)

    return prices


def _generate_scraped_dates(
    num_records: int,
    days_back: int = 30,
) -> list[datetime]:
    """Genera fechas de scraped_at distribuidas en los últimos N días.

    Las fechas se distribuyen de forma aproximadamente uniforme,
    simulando ejecuciones del pipeline cada ~7 días (3-5 veces en 30 días).
    Se añade una hora aleatoria para simular diferentes momentos del día.

    Args:
        num_records: Número de fechas a generar
        days_back:   Días hacia atrás desde hoy

    Returns:
        Lista de datetimes con timezone UTC, ordenados de más antiguo a más reciente
    """
    now = datetime.now(timezone.utc)
    dates: list[datetime] = []

    # Distribuir los registros uniformemente en el periodo
    if num_records <= 1:
        dates.append(now - timedelta(days=days_back // 2))
    else:
        interval = days_back / (num_records - 1) if num_records > 1 else days_back
        for i in range(num_records):
            days_ago = days_back - (i * interval)
            hour = random.randint(6, 22)  # Horario laboral
            minute = random.randint(0, 59)
            second = random.randint(0, 59)

            dt = now - timedelta(days=days_ago)
            dt = dt.replace(hour=hour, minute=minute, second=second, microsecond=0)
            dates.append(dt)

    # Ordenar cronológicamente
    dates.sort()
    return dates


# ---------------------------------------------------------------------------
# Funciones de inserción idempotente
# ---------------------------------------------------------------------------
def _insert_stores(session: Session) -> dict[str, int]:
    """Inserta las 3 tiendas si no existen.

    Usa session.merge() para idempotencia: si la tienda ya existe
    (por unique constraint en name), se actualiza; si no, se inserta.

    Args:
        session: Sesión SQLAlchemy activa

    Returns:
        Diccionario {store_name: store_id} con los IDs
    """
    store_ids: dict[str, int] = {}

    for store_data in SEED_STORES:
        # Buscar existente
        existing = session.query(Store).filter(
            Store.name == store_data["name"]
        ).first()

        if existing:
            store_ids[store_data["name"]] = existing.id
            logger.debug(f"Tienda ya existe: {store_data['name']} (id={existing.id})")
        else:
            new_store = Store(
                name=store_data["name"],
                country=store_data["country"],
            )
            session.add(new_store)
            session.flush()  # Obtener ID asignado
            store_ids[store_data["name"]] = new_store.id
            logger.info(f"Tienda insertada: {store_data['name']} (id={new_store.id})")

    return store_ids


def _insert_categories(session: Session) -> dict[str, int]:
    """Inserta las 7 categorías si no existen.

    Args:
        session: Sesión SQLAlchemy activa

    Returns:
        Diccionario {category_name: category_id} con los IDs
    """
    category_ids: dict[str, int] = {}

    for cat_name in SEED_CATEGORIES:
        existing = session.query(Category).filter(
            Category.name == cat_name
        ).first()

        if existing:
            category_ids[cat_name] = existing.id
            logger.debug(f"Categoría ya existe: {cat_name} (id={existing.id})")
        else:
            new_cat = Category(name=cat_name)
            session.add(new_cat)
            session.flush()
            category_ids[cat_name] = new_cat.id
            logger.info(f"Categoría insertada: {cat_name} (id={new_cat.id})")

    return category_ids


def _upsert_product(
    session: Session,
    name: str,
    brand: str,
    url: str | None,
    sku: str | None,
    category_id: int,
    store_id: int,
) -> Product:
    """Inserta o actualiza un producto por (name, store_id).

    Si el producto ya existe, se actualizan brand, url y sku.
    Si no existe, se inserta como nuevo.

    Args:
        session:     Sesión SQLAlchemy activa
        name:        Nombre del producto
        brand:       Marca
        url:         URL del producto
        sku:         SKU del producto
        category_id: ID de la categoría
        store_id:    ID de la tienda

    Returns:
        Instancia de Product (nueva o existente)
    """
    existing = session.query(Product).filter(
        and_(
            Product.name == name,
            Product.store_id == store_id,
        )
    ).first()

    if existing:
        # Actualizar campos mutables
        existing.brand = brand
        existing.url = url
        existing.sku = sku
        existing.category_id = category_id
        return existing
    else:
        new_product = Product(
            name=name,
            brand=brand,
            url=url,
            sku=sku,
            category_id=category_id,
            store_id=store_id,
        )
        session.add(new_product)
        session.flush()
        return new_product


def _insert_price_history_record(
    session: Session,
    product_id: int,
    price: float,
    scraped_at: datetime,
    price_change: float | None,
    price_change_pct: float | None,
) -> bool:
    """Inserta un registro de precio si no existe para esa fecha.

    Deduplicación: solo un registro por (product_id, fecha).
    Si ya existe un registro para el mismo producto en el mismo día,
    se omite la inserción.

    Args:
        session:         Sesión SQLAlchemy activa
        product_id:      ID del producto
        price:           Precio en MXN
        scraped_at:      Fecha y hora del registro
        price_change:    Cambio absoluto vs registro anterior
        price_change_pct: Cambio porcentual vs registro anterior

    Returns:
        True si se insertó, False si se omitió (duplicado)
    """
    # Verificar si ya existe registro para ese día
    day_start = scraped_at.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = scraped_at.replace(hour=23, minute=59, second=59, microsecond=999999)

    existing = session.query(PriceHistory).filter(
        and_(
            PriceHistory.product_id == product_id,
            PriceHistory.scraped_at >= day_start,
            PriceHistory.scraped_at <= day_end,
        )
    ).first()

    if existing:
        return False  # Duplicado — omitir

    price_record = PriceHistory(
        product_id=product_id,
        price=price,
        currency="MXN",
        availability=True,
        price_change=price_change,
        price_change_pct=price_change_pct,
        scraped_at=scraped_at,
    )
    session.add(price_record)
    session.flush()
    return True


# ---------------------------------------------------------------------------
# Función principal de seeding
# ---------------------------------------------------------------------------
def seed_all() -> dict[str, Any]:
    """Ejecuta el seeding completo de la base de datos.

    Flujo:
        1. Verificar conexión a BD
        2. Crear tablas si no existen (init_db)
        3. Insertar tiendas (3)
        4. Insertar categorías (7)
        5. Insertar productos (105 = 35 productos × 3 tiendas)
        6. Insertar historial de precios (3-5 registros por producto)

    Returns:
        Diccionario con métricas del seeding:
            - stores_inserted: Tiendas insertadas nuevas
            - categories_inserted: Categorías insertadas nuevas
            - products_inserted: Productos insertados nuevos
            - products_updated: Productos actualizados (ya existían)
            - prices_inserted: Registros de precio insertados
            - prices_skipped: Registros de precio omitidos (duplicados)
            - total_products: Total de productos en BD
            - total_prices: Total de registros de precio en BD
    """
    logger.info("=" * 60)
    logger.info("PricePulse Analytics — Script de Datos Semilla")
    logger.info("=" * 60)

    # ── 1. Verificar conexión ─────────────────────────────────────────
    dialect = settings.database.dialect_name.upper()

    if not check_connection():
        if settings.database.is_sqlite:
            logger.error(f"No se pudo crear/acceder a la base de datos SQLite.")
        else:
            logger.error(f"No se pudo conectar a PostgreSQL. ¿Está corriendo el servidor?")
        logger.info(
            f"Configuración actual: dialect={dialect}, "
            f"url={settings.database.url}"
        )
        return {"error": f"No se pudo conectar a {dialect}"}

    # ── 2. Inicializar tablas ─────────────────────────────────────────
    logger.info("Verificando/creando tablas...")
    init_db()

    # ── Contadores ────────────────────────────────────────────────────
    metrics = {
        "stores_inserted": 0,
        "categories_inserted": 0,
        "products_inserted": 0,
        "products_updated": 0,
        "prices_inserted": 0,
        "prices_skipped": 0,
        "total_products": 0,
        "total_prices": 0,
    }

    with get_session() as session:
        # ── 3. Insertar tiendas ───────────────────────────────────────
        logger.info("--- Insertando tiendas ---")
        store_ids = _insert_stores(session)
        metrics["stores_inserted"] = len(store_ids)

        # ── 4. Insertar categorías ────────────────────────────────────
        logger.info("--- Insertando categorías ---")
        category_ids = _insert_categories(session)
        metrics["categories_inserted"] = len(category_ids)

        # ── 5. Insertar productos ─────────────────────────────────────
        logger.info("--- Insertando productos ---")

        # Tendencias de precio por producto (para series realistas)
        trends = ["up", "down", "stable", "mixed"]

        for product_def in SEED_PRODUCTS:
            category_name = product_def["category"]
            category_id = category_ids.get(category_name)

            if category_id is None:
                logger.warning(
                    f"Categoría '{category_name}' no encontrada — omitiendo producto"
                )
                continue

            # Elegir tendencia aleatoria para este producto
            product_trend = random.choice(trends)

            # Número de registros de historial (3-5)
            num_price_records = random.randint(3, 5)

            for store_name, store_id in store_ids.items():
                # Determinar URL y SKU según la tienda
                if store_name == "Mercado Libre":
                    url = product_def.get("url_ml")
                    sku = product_def.get("sku_ml")
                elif store_name == "AliExpress":
                    url = product_def.get("url_ae")
                    sku = product_def.get("sku_ae")
                else:  # Temu
                    url = product_def.get("url_temu", product_def.get("url_ae"))
                    sku = product_def.get("sku_temu", product_def.get("sku_ae"))

                # Upsert del producto
                existing_before = session.query(Product).filter(
                    and_(
                        Product.name == product_def["name"],
                        Product.store_id == store_id,
                    )
                ).first()

                product = _upsert_product(
                    session=session,
                    name=product_def["name"],
                    brand=product_def["brand"],
                    url=url,
                    sku=sku,
                    category_id=category_id,
                    store_id=store_id,
                )

                if existing_before:
                    metrics["products_updated"] += 1
                else:
                    metrics["products_inserted"] += 1

                # ── 6. Insertar historial de precios ──────────────────
                price_series = _generate_price_series(
                    base_price=product_def["base_price_mx"],
                    num_records=num_price_records,
                    store_name=store_name,
                    trend=product_trend,
                )

                scraped_dates = _generate_scraped_dates(
                    num_records=num_price_records,
                    days_back=30,
                )

                for idx, (price, scraped_at) in enumerate(
                    zip(price_series, scraped_dates)
                ):
                    # Validar que el precio esté en rango
                    if not PriceValidation.is_valid_price(category_name, price):
                        logger.warning(
                            f"Precio fuera de rango para {product_def['name'][:40]} "
                            f"en {store_name}: ${price:,.2f} MXN — ajustando"
                        )
                        # Ajustar al límite más cercano
                        min_price, max_price = PriceValidation.RANGES[category_name]
                        price = max(min_price, min(max_price, price))

                    # Calcular price_change vs registro anterior
                    if idx == 0:
                        # Primer registro: verificar si ya hay registros previos en BD
                        last_existing = session.query(PriceHistory).filter(
                            PriceHistory.product_id == product.id
                        ).order_by(PriceHistory.scraped_at.desc()).first()

                        if last_existing and last_existing.scraped_at < scraped_at:
                            price_change = round(price - last_existing.price, 2)
                            price_change_pct = (
                                round(
                                    ((price - last_existing.price)
                                     / last_existing.price) * 100,
                                    2,
                                )
                                if last_existing.price > 0
                                else None
                            )
                        else:
                            price_change = None
                            price_change_pct = None
                    else:
                        # Comparar con el precio anterior de la serie
                        prev_price = price_series[idx - 1]
                        price_change = round(price - prev_price, 2)
                        price_change_pct = (
                            round(
                                ((price - prev_price) / prev_price) * 100,
                                2,
                            )
                            if prev_price > 0
                            else None
                        )

                    inserted = _insert_price_history_record(
                        session=session,
                        product_id=product.id,
                        price=price,
                        scraped_at=scraped_at,
                        price_change=price_change,
                        price_change_pct=price_change_pct,
                    )

                    if inserted:
                        metrics["prices_inserted"] += 1
                    else:
                        metrics["prices_skipped"] += 1

        # ── Contar totales finales ────────────────────────────────────
        metrics["total_products"] = session.query(Product).count()
        metrics["total_prices"] = session.query(PriceHistory).count()

    # ── Resumen ───────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("Seeding completado exitosamente")
    logger.info("-" * 60)
    logger.info(f"  Tiendas:     {metrics['stores_inserted']} (3 esperadas)")
    logger.info(f"  Categorías:  {metrics['categories_inserted']} (7 esperadas)")
    logger.info(f"  Productos:   {metrics['products_inserted']} nuevos + "
                f"{metrics['products_updated']} actualizados = "
                f"{metrics['total_products']} total")
    logger.info(f"  Precios:     {metrics['prices_inserted']} insertados, "
                f"{metrics['prices_skipped']} omitidos (duplicados) = "
                f"{metrics['total_prices']} total")
    logger.info("=" * 60)

    return metrics


# ---------------------------------------------------------------------------
# Punto de entrada CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        result = seed_all()

        if "error" in result:
            logger.error(f"Error: {result['error']}")
            sys.exit(1)

        logger.info(f"Métricas finales: {result}")

    except KeyboardInterrupt:
        logger.warning("Seeding interrumpido por el usuario")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"Error fatal durante seeding: {e}")
        sys.exit(1)
