"""
SQLAlchemy models matching the Part 2 database schema.
These can be used with Flask-SQLAlchemy or standalone SQLAlchemy.
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

# Note: The SQL DDL (schema.sql) uses BIGSERIAL for PostgreSQL production use.
# Here we use Integer for SQLite compatibility in development/testing.
# SQLAlchemy's Integer maps to BIGINT on PostgreSQL when needed.

db = SQLAlchemy()


# ──────────────────────────────────────────────
# A. Companies
# ──────────────────────────────────────────────

class Company(db.Model):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    users = relationship("User", back_populates="company", cascade="all, delete-orphan")
    warehouses = relationship("Warehouse", back_populates="company", cascade="all, delete-orphan")
    products = relationship("Product", back_populates="company", cascade="all, delete-orphan")
    suppliers = relationship("Supplier", back_populates="company", cascade="all, delete-orphan")


# ──────────────────────────────────────────────
# B. Users
# ──────────────────────────────────────────────

class User(db.Model):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="staff")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    company = relationship("Company", back_populates="users")

    __table_args__ = (
        CheckConstraint("role IN ('admin', 'manager', 'staff')", name="ck_users_role"),
        Index("idx_users_company", "company_id"),
    )


# ──────────────────────────────────────────────
# C. Warehouses
# ──────────────────────────────────────────────

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


# ──────────────────────────────────────────────
# D. Products
# ──────────────────────────────────────────────

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

    # Bundle relationships
    bundle_components = relationship(
        "BundleComponent",
        foreign_keys="BundleComponent.bundle_product_id",
        back_populates="bundle",
        cascade="all, delete-orphan",
    )
    part_of_bundles = relationship(
        "BundleComponent",
        foreign_keys="BundleComponent.component_product_id",
        back_populates="component",
    )

    __table_args__ = (
        UniqueConstraint("company_id", "sku", name="uq_product_company_sku"),
        CheckConstraint("price >= 0", name="ck_products_price"),
        CheckConstraint("product_type IN ('normal', 'bundle')", name="ck_products_type"),
        Index("idx_products_company", "company_id"),
        Index("idx_products_sku", "sku"),
    )


# ──────────────────────────────────────────────
# E. Suppliers
# ──────────────────────────────────────────────

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


# ──────────────────────────────────────────────
# F. Product-Supplier (many-to-many)
# ──────────────────────────────────────────────

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


# ──────────────────────────────────────────────
# G. Inventory
# ──────────────────────────────────────────────

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


# ──────────────────────────────────────────────
# H. Inventory Movements (audit log)
# ──────────────────────────────────────────────

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
    performed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    inventory = relationship("Inventory", back_populates="movements")
    performer = relationship("User")

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


# ──────────────────────────────────────────────
# I. Bundle Components
# ──────────────────────────────────────────────

class BundleComponent(db.Model):
    __tablename__ = "bundle_components"

    bundle_product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    component_product_id = Column(Integer, ForeignKey("products.id", ondelete="RESTRICT"), primary_key=True)
    component_quantity = Column(Integer, nullable=False)

    bundle = relationship("Product", foreign_keys=[bundle_product_id], back_populates="bundle_components")
    component = relationship("Product", foreign_keys=[component_product_id], back_populates="part_of_bundles")

    __table_args__ = (
        CheckConstraint("component_quantity > 0", name="ck_bundle_qty"),
        CheckConstraint("bundle_product_id <> component_product_id", name="ck_bundle_no_self_ref"),
    )


# ──────────────────────────────────────────────
# J. Warehouse Transfers
# ──────────────────────────────────────────────

class WarehouseTransfer(db.Model):
    __tablename__ = "warehouse_transfers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    source_warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False)
    dest_warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False)
    quantity = Column(Integer, nullable=False)
    status = Column(String(50), nullable=False, default="pending")
    initiated_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    product = relationship("Product")
    source_warehouse = relationship("Warehouse", foreign_keys=[source_warehouse_id])
    dest_warehouse = relationship("Warehouse", foreign_keys=[dest_warehouse_id])
    initiator = relationship("User")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_transfer_qty"),
        CheckConstraint("source_warehouse_id <> dest_warehouse_id", name="ck_transfer_diff_wh"),
        CheckConstraint(
            "status IN ('pending', 'in_transit', 'completed', 'cancelled')",
            name="ck_transfer_status",
        ),
        Index("idx_transfers_product", "product_id"),
        Index("idx_transfers_source", "source_warehouse_id"),
        Index("idx_transfers_dest", "dest_warehouse_id"),
    )
