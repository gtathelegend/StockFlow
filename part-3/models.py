"""
Reuses the Part 2 schema models.
Copied here so Part 3 is self-contained and runnable independently.
"""

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    CheckConstraint,
    Index,
    func,
)
from sqlalchemy.orm import relationship

db = SQLAlchemy()


class Company(db.Model):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    warehouses = relationship("Warehouse", back_populates="company", cascade="all, delete-orphan")
    products = relationship("Product", back_populates="company", cascade="all, delete-orphan")
    suppliers = relationship("Supplier", back_populates="company", cascade="all, delete-orphan")


class Warehouse(db.Model):
    __tablename__ = "warehouses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    location = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    company = relationship("Company", back_populates="warehouses")
    inventories = relationship("Inventory", back_populates="warehouse")

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_warehouse_company_name"),
        Index("idx_warehouses_company", "company_id"),
    )


class Product(db.Model):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    sku = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Numeric(12, 2), nullable=False, default=0.00)
    product_type = Column(String(50), nullable=False, default="normal")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    company = relationship("Company", back_populates="products")
    inventories = relationship("Inventory", back_populates="product")
    suppliers = relationship("ProductSupplier", back_populates="product")

    __table_args__ = (
        UniqueConstraint("company_id", "sku", name="uq_product_company_sku"),
        CheckConstraint("price >= 0", name="ck_products_price"),
        CheckConstraint("product_type IN ('normal', 'bundle')", name="ck_products_type"),
        Index("idx_products_company", "company_id"),
        Index("idx_products_sku", "sku"),
    )


class Supplier(db.Model):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    contact_email = Column(String(255), nullable=True)
    contact_phone = Column(String(50), nullable=True)
    address = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    company = relationship("Company", back_populates="suppliers")
    products = relationship("ProductSupplier", back_populates="supplier")

    __table_args__ = (
        Index("idx_suppliers_company", "company_id"),
    )


class ProductSupplier(db.Model):
    __tablename__ = "product_suppliers"

    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id", ondelete="CASCADE"), primary_key=True)
    supplier_sku = Column(String(100), nullable=True)
    lead_time_days = Column(Integer, nullable=True)
    cost_price = Column(Numeric(12, 2), nullable=True)
    is_primary = Column(Boolean, nullable=False, default=False)

    product = relationship("Product", back_populates="suppliers")
    supplier = relationship("Supplier", back_populates="products")

    __table_args__ = (
        CheckConstraint("lead_time_days IS NULL OR lead_time_days >= 0", name="ck_ps_lead_time"),
        CheckConstraint("cost_price IS NULL OR cost_price >= 0", name="ck_ps_cost_price"),
    )


class Inventory(db.Model):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False)
    quantity = Column(Integer, nullable=False, default=0)
    reserved_quantity = Column(Integer, nullable=False, default=0)
    reorder_level = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    product = relationship("Product", back_populates="inventories")
    warehouse = relationship("Warehouse", back_populates="inventories")
    movements = relationship("InventoryMovement", back_populates="inventory")

    __table_args__ = (
        UniqueConstraint("product_id", "warehouse_id", name="uq_inventory_product_warehouse"),
        CheckConstraint("quantity >= 0", name="ck_inventory_qty"),
        CheckConstraint("reserved_quantity >= 0", name="ck_inventory_reserved"),
        CheckConstraint("reserved_quantity <= quantity", name="ck_inventory_reserved_lte_qty"),
        Index("idx_inventory_warehouse", "warehouse_id"),
        Index("idx_inventory_product", "product_id"),
    )


class InventoryMovement(db.Model):
    __tablename__ = "inventory_movements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    inventory_id = Column(Integer, ForeignKey("inventory.id", ondelete="RESTRICT"), nullable=False)
    change_type = Column(String(50), nullable=False)
    quantity_change = Column(Integer, nullable=False)
    quantity_before = Column(Integer, nullable=False)
    quantity_after = Column(Integer, nullable=False)
    reference_type = Column(String(100), nullable=True)
    reference_id = Column(Integer, nullable=True)
    performed_by = Column(Integer, nullable=True)  # FK to users.id (omitted here for standalone use)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    inventory = relationship("Inventory", back_populates="movements")

    __table_args__ = (
        CheckConstraint("quantity_change <> 0", name="ck_movements_nonzero"),
        CheckConstraint("quantity_after >= 0", name="ck_movements_after_positive"),
        CheckConstraint(
            "change_type IN ('purchase', 'sale', 'return', 'adjustment', "
            "'transfer_in', 'transfer_out', 'damaged', 'bundle_assembly')",
            name="ck_movements_type",
        ),
        Index("idx_movements_inventory", "inventory_id"),
        Index("idx_movements_created", "created_at"),
        Index("idx_movements_reference", "reference_type", "reference_id"),
        Index("idx_movements_performer", "performed_by"),
    )
