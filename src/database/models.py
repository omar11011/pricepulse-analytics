"""Modelos ORM — 5 tablas: Store, Category, Product, PriceHistory, PipelineLog."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    Index,
    Boolean,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


# ---
# Base
# ---
class Base(DeclarativeBase):
    """Base ORM para todos los modelos."""

    pass


# ---
# Store
# ---
class Store(Base):
    """Tienda online — nombre único + país."""

    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    country: Mapped[str] = mapped_column(String(50), nullable=False, default="México")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # --- Relaciones ---
    products: Mapped[list["Product"]] = relationship(
        "Product", back_populates="store", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Store(id={self.id}, name='{self.name}', country='{self.country}')>"

    def __str__(self) -> str:
        return self.name


# ---
# Category
# ---
class Category(Base):
    """Categoría de producto — las 7 del MVP."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)

    # --- Relaciones ---
    products: Mapped[list["Product"]] = relationship(
        "Product", back_populates="category", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Category(id={self.id}, name='{self.name}')>"

    def __str__(self) -> str:
        return self.name


# ---
# Product
# ---
class Product(Base):
    """Producto — único por (name, store_id), soporta upsert."""

    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("name", "store_id", name="uq_product_name_store"),
        Index("ix_products_category_id", "category_id"),
        Index("ix_products_store_id", "store_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False
    )
    store_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # --- Relaciones ---
    store: Mapped["Store"] = relationship("Store", back_populates="products")
    category: Mapped["Category"] = relationship("Category", back_populates="products")
    price_history: Mapped[list["PriceHistory"]] = relationship(
        "PriceHistory", back_populates="product", lazy="selectin",
        order_by="PriceHistory.scraped_at.desc()",
    )

    def __repr__(self) -> str:
        return f"<Product(id={self.id}, name='{self.name[:50]}', store_id={self.store_id})>"

    def __str__(self) -> str:
        return self.name


# ---
# PriceHistory
# ---
class PriceHistory(Base):
    """Historial de precios — un registro por (product_id, scraped_at). price_change/price_change_pct son Nullable (primer registro no tiene anterior)."""

    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint("product_id", "scraped_at", name="uq_price_product_date"),
        Index("ix_price_history_product_id", "product_id"),
        Index("ix_price_history_scraped_at", "scraped_at"),
        Index("ix_price_history_product_date", "product_id", "scraped_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    price: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="MXN")
    availability: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    price_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # --- Relaciones ---
    product: Mapped["Product"] = relationship("Product", back_populates="price_history")

    def __repr__(self) -> str:
        return (
            f"<PriceHistory(id={self.id}, product_id={self.product_id}, "
            f"price={self.price}, scraped_at={self.scraped_at})>"
        )


# ---
# PipelineLog
# ---
class PipelineLog(Base):
    """Log de ejecución ETL — status, métricas, execution_time_ms."""

    __tablename__ = "pipeline_logs"
    __table_args__ = (
        Index("ix_pipeline_logs_created_at", "created_at"),
        Index("ix_pipeline_logs_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    process_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    products_found: Mapped[int | None] = mapped_column(Integer, nullable=True)
    products_saved: Mapped[int | None] = mapped_column(Integer, nullable=True)
    products_failed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<PipelineLog(id={self.id}, process='{self.process_name}', "
            f"status='{self.status}')>"
        )


# ---
# Exportación
# ---
__all__ = [
    "Base",
    "Store",
    "Category",
    "Product",
    "PriceHistory",
    "PipelineLog",
]
