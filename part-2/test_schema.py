"""
Tests verifying schema constraints, relationships, and data integrity.
Uses an in-memory SQLite database with Flask-SQLAlchemy.
"""

import pytest
from decimal import Decimal
from flask import Flask
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

from models import (
    db,
    Company,
    User,
    Warehouse,
    Product,
    Supplier,
    ProductSupplier,
    Inventory,
    InventoryMovement,
    BundleComponent,
    WarehouseTransfer,
)


def _enable_sqlite_fk(dbapi_conn, connection_record):
    """SQLite ignores FK constraints by default. This enables them."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["TESTING"] = True
    db.init_app(app)
    with app.app_context():
        # Enable foreign key enforcement for SQLite
        event.listen(db.engine, "connect", _enable_sqlite_fk)
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def session(app):
    with app.app_context():
        yield db.session


@pytest.fixture
def company(session):
    c = Company(name="Acme Corp")
    session.add(c)
    session.commit()
    return c


@pytest.fixture
def user(session, company):
    u = User(company_id=company.id, email="alice@acme.com", name="Alice", role="admin")
    session.add(u)
    session.commit()
    return u


@pytest.fixture
def warehouses(session, company):
    wh1 = Warehouse(company_id=company.id, name="East", location="New York")
    wh2 = Warehouse(company_id=company.id, name="West", location="Los Angeles")
    session.add_all([wh1, wh2])
    session.commit()
    return wh1, wh2


@pytest.fixture
def product(session, company):
    p = Product(company_id=company.id, name="Widget", sku="WDG-001", price=Decimal("19.99"))
    session.add(p)
    session.commit()
    return p


@pytest.fixture
def supplier(session, company):
    s = Supplier(company_id=company.id, name="Parts Inc", contact_email="info@parts.com")
    session.add(s)
    session.commit()
    return s


# ──────────────────────────────────────────────
# Company tests
# ──────────────────────────────────────────────

class TestCompany:

    def test_create_company(self, session, company):
        assert company.id is not None
        assert company.name == "Acme Corp"

    def test_company_has_relationships(self, session, company):
        assert company.users == []
        assert company.warehouses == []
        assert company.products == []
        assert company.suppliers == []


# ──────────────────────────────────────────────
# User tests
# ──────────────────────────────────────────────

class TestUser:

    def test_create_user(self, session, user):
        assert user.id is not None
        assert user.role == "admin"

    def test_duplicate_email_rejected(self, session, company, user):
        u2 = User(company_id=company.id, email="alice@acme.com", name="Alice2", role="staff")
        session.add(u2)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_user_belongs_to_company(self, session, user, company):
        assert user.company_id == company.id
        assert user in company.users


# ──────────────────────────────────────────────
# Warehouse tests
# ──────────────────────────────────────────────

class TestWarehouse:

    def test_create_warehouse(self, session, warehouses):
        wh1, wh2 = warehouses
        assert wh1.name == "East"
        assert wh2.location == "Los Angeles"

    def test_multiple_warehouses_per_company(self, session, company, warehouses):
        assert len(company.warehouses) == 2

    def test_duplicate_name_same_company_rejected(self, session, company, warehouses):
        dup = Warehouse(company_id=company.id, name="East", location="Other")
        session.add(dup)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_same_name_different_company_allowed(self, session, warehouses):
        c2 = Company(name="Other Corp")
        session.add(c2)
        session.commit()
        wh = Warehouse(company_id=c2.id, name="East", location="Boston")
        session.add(wh)
        session.commit()  # Should not raise
        assert wh.id is not None


# ──────────────────────────────────────────────
# Product tests
# ──────────────────────────────────────────────

class TestProduct:

    def test_create_product(self, session, product):
        assert product.id is not None
        assert product.price == Decimal("19.99")
        assert product.product_type == "normal"

    def test_duplicate_sku_same_company_rejected(self, session, company, product):
        dup = Product(company_id=company.id, name="Other", sku="WDG-001", price=Decimal("5.00"))
        session.add(dup)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_same_sku_different_company_allowed(self, session, product):
        c2 = Company(name="Other Corp")
        session.add(c2)
        session.commit()
        p2 = Product(company_id=c2.id, name="Other Widget", sku="WDG-001", price=Decimal("9.99"))
        session.add(p2)
        session.commit()  # Should not raise
        assert p2.id is not None

    def test_product_belongs_to_company(self, session, product, company):
        assert product.company_id == company.id
        assert product in company.products

    def test_decimal_price_precision(self, session, company):
        p = Product(company_id=company.id, name="Precise", sku="PRC-001", price=Decimal("999999999.99"))
        session.add(p)
        session.commit()
        assert p.price == Decimal("999999999.99")


# ──────────────────────────────────────────────
# Supplier tests
# ──────────────────────────────────────────────

class TestSupplier:

    def test_create_supplier(self, session, supplier):
        assert supplier.id is not None
        assert supplier.name == "Parts Inc"

    def test_supplier_scoped_to_company(self, session, supplier, company):
        assert supplier.company_id == company.id
        assert supplier in company.suppliers


# ──────────────────────────────────────────────
# Product-Supplier tests
# ──────────────────────────────────────────────

class TestProductSupplier:

    def test_link_product_to_supplier(self, session, product, supplier):
        ps = ProductSupplier(
            product_id=product.id,
            supplier_id=supplier.id,
            supplier_sku="SUP-WDG",
            lead_time_days=7,
            cost_price=Decimal("12.00"),
            is_primary=True,
        )
        session.add(ps)
        session.commit()
        assert len(product.suppliers) == 1
        assert product.suppliers[0].supplier_sku == "SUP-WDG"

    def test_multiple_suppliers_per_product(self, session, company, product):
        s1 = Supplier(company_id=company.id, name="Supplier A")
        s2 = Supplier(company_id=company.id, name="Supplier B")
        session.add_all([s1, s2])
        session.commit()

        session.add(ProductSupplier(product_id=product.id, supplier_id=s1.id))
        session.add(ProductSupplier(product_id=product.id, supplier_id=s2.id))
        session.commit()
        assert len(product.suppliers) == 2

    def test_duplicate_product_supplier_rejected(self, session, product, supplier):
        session.add(ProductSupplier(product_id=product.id, supplier_id=supplier.id))
        session.commit()
        session.add(ProductSupplier(product_id=product.id, supplier_id=supplier.id))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


# ──────────────────────────────────────────────
# Inventory tests
# ──────────────────────────────────────────────

class TestInventory:

    def test_create_inventory(self, session, product, warehouses):
        wh1, _ = warehouses
        inv = Inventory(product_id=product.id, warehouse_id=wh1.id, quantity=100)
        session.add(inv)
        session.commit()
        assert inv.id is not None
        assert inv.quantity == 100
        assert inv.reserved_quantity == 0

    def test_product_in_multiple_warehouses(self, session, product, warehouses):
        wh1, wh2 = warehouses
        session.add(Inventory(product_id=product.id, warehouse_id=wh1.id, quantity=50))
        session.add(Inventory(product_id=product.id, warehouse_id=wh2.id, quantity=30))
        session.commit()
        assert len(product.inventories) == 2

    def test_duplicate_product_warehouse_rejected(self, session, product, warehouses):
        wh1, _ = warehouses
        session.add(Inventory(product_id=product.id, warehouse_id=wh1.id, quantity=10))
        session.commit()
        session.add(Inventory(product_id=product.id, warehouse_id=wh1.id, quantity=20))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_delete_product_with_inventory_blocked(self, session, product, warehouses):
        """ON DELETE RESTRICT prevents deleting a product that has inventory."""
        wh1, _ = warehouses
        session.add(Inventory(product_id=product.id, warehouse_id=wh1.id, quantity=10))
        session.commit()
        session.delete(product)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_delete_warehouse_with_inventory_blocked(self, session, product, warehouses):
        """ON DELETE RESTRICT prevents deleting a warehouse that has inventory."""
        wh1, _ = warehouses
        session.add(Inventory(product_id=product.id, warehouse_id=wh1.id, quantity=10))
        session.commit()
        session.delete(wh1)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


# ──────────────────────────────────────────────
# Inventory Movement tests
# ──────────────────────────────────────────────

class TestInventoryMovement:

    def test_create_movement(self, session, product, warehouses, user):
        wh1, _ = warehouses
        inv = Inventory(product_id=product.id, warehouse_id=wh1.id, quantity=100)
        session.add(inv)
        session.commit()

        mov = InventoryMovement(
            inventory_id=inv.id,
            change_type="purchase",
            quantity_change=100,
            quantity_before=0,
            quantity_after=100,
            performed_by=user.id,
            note="Initial stock",
        )
        session.add(mov)
        session.commit()
        assert mov.id is not None
        assert mov.performer.name == "Alice"

    def test_movement_linked_to_inventory(self, session, product, warehouses):
        wh1, _ = warehouses
        inv = Inventory(product_id=product.id, warehouse_id=wh1.id, quantity=50)
        session.add(inv)
        session.commit()

        session.add(InventoryMovement(
            inventory_id=inv.id, change_type="purchase",
            quantity_change=50, quantity_before=0, quantity_after=50,
        ))
        session.add(InventoryMovement(
            inventory_id=inv.id, change_type="sale",
            quantity_change=-10, quantity_before=50, quantity_after=40,
        ))
        session.commit()
        assert len(inv.movements) == 2

    def test_delete_inventory_with_movements_blocked(self, session, product, warehouses):
        """ON DELETE RESTRICT prevents deleting inventory that has movement history."""
        wh1, _ = warehouses
        inv = Inventory(product_id=product.id, warehouse_id=wh1.id, quantity=50)
        session.add(inv)
        session.commit()

        session.add(InventoryMovement(
            inventory_id=inv.id, change_type="purchase",
            quantity_change=50, quantity_before=0, quantity_after=50,
        ))
        session.commit()

        session.delete(inv)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


# ──────────────────────────────────────────────
# Bundle Component tests
# ──────────────────────────────────────────────

class TestBundleComponent:

    def test_create_bundle(self, session, company):
        comp1 = Product(company_id=company.id, name="Part A", sku="PA-001", price=Decimal("5.00"))
        comp2 = Product(company_id=company.id, name="Part B", sku="PB-001", price=Decimal("3.00"))
        bundle = Product(
            company_id=company.id, name="Bundle AB", sku="BND-001",
            price=Decimal("10.00"), product_type="bundle",
        )
        session.add_all([comp1, comp2, bundle])
        session.commit()

        session.add(BundleComponent(bundle_product_id=bundle.id, component_product_id=comp1.id, component_quantity=2))
        session.add(BundleComponent(bundle_product_id=bundle.id, component_product_id=comp2.id, component_quantity=1))
        session.commit()

        assert len(bundle.bundle_components) == 2
        assert bundle.bundle_components[0].component_quantity == 2

    def test_component_knows_its_bundles(self, session, company):
        comp = Product(company_id=company.id, name="Part X", sku="PX-001", price=Decimal("5.00"))
        b1 = Product(company_id=company.id, name="Bundle 1", sku="B1", price=Decimal("10.00"), product_type="bundle")
        b2 = Product(company_id=company.id, name="Bundle 2", sku="B2", price=Decimal("15.00"), product_type="bundle")
        session.add_all([comp, b1, b2])
        session.commit()

        session.add(BundleComponent(bundle_product_id=b1.id, component_product_id=comp.id, component_quantity=1))
        session.add(BundleComponent(bundle_product_id=b2.id, component_product_id=comp.id, component_quantity=3))
        session.commit()
        assert len(comp.part_of_bundles) == 2

    def test_self_reference_blocked(self, session, product):
        """A product cannot be a component of itself."""
        bc = BundleComponent(bundle_product_id=product.id, component_product_id=product.id, component_quantity=1)
        session.add(bc)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_delete_component_with_bundles_blocked(self, session, company):
        """ON DELETE RESTRICT on component prevents deleting a product used in bundles.
        SQLAlchemy's ORM may raise AssertionError (trying to null a composite PK)
        before the DB-level IntegrityError fires, so we catch both."""
        comp = Product(company_id=company.id, name="Critical Part", sku="CP-001", price=Decimal("5.00"))
        bundle = Product(company_id=company.id, name="Bundle", sku="BND-X", price=Decimal("10.00"), product_type="bundle")
        session.add_all([comp, bundle])
        session.commit()
        session.add(BundleComponent(bundle_product_id=bundle.id, component_product_id=comp.id, component_quantity=1))
        session.commit()

        session.delete(comp)
        with pytest.raises((IntegrityError, AssertionError)):
            session.commit()
        session.rollback()


# ──────────────────────────────────────────────
# Warehouse Transfer tests
# ──────────────────────────────────────────────

class TestWarehouseTransfer:

    def test_create_transfer(self, session, product, warehouses, user):
        wh1, wh2 = warehouses
        t = WarehouseTransfer(
            product_id=product.id,
            source_warehouse_id=wh1.id,
            dest_warehouse_id=wh2.id,
            quantity=25,
            initiated_by=user.id,
        )
        session.add(t)
        session.commit()
        assert t.id is not None
        assert t.status == "pending"
        assert t.source_warehouse.name == "East"
        assert t.dest_warehouse.name == "West"

    def test_transfer_same_warehouse_blocked(self, session, product, warehouses):
        """Cannot transfer to the same warehouse."""
        wh1, _ = warehouses
        t = WarehouseTransfer(
            product_id=product.id,
            source_warehouse_id=wh1.id,
            dest_warehouse_id=wh1.id,
            quantity=10,
        )
        session.add(t)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


# ──────────────────────────────────────────────
# Cross-cutting / integration tests
# ──────────────────────────────────────────────

class TestIntegration:

    def test_full_product_lifecycle(self, session, company, user):
        """Create company -> warehouse -> product -> inventory -> movement."""
        wh = Warehouse(company_id=company.id, name="Main", location="HQ")
        session.add(wh)
        session.commit()

        p = Product(company_id=company.id, name="Gadget", sku="GDG-001", price=Decimal("49.99"))
        session.add(p)
        session.commit()

        inv = Inventory(product_id=p.id, warehouse_id=wh.id, quantity=200)
        session.add(inv)
        session.commit()

        mov = InventoryMovement(
            inventory_id=inv.id, change_type="purchase",
            quantity_change=200, quantity_before=0, quantity_after=200,
            performed_by=user.id, note="Initial purchase order",
        )
        session.add(mov)
        session.commit()

        # Verify chain
        assert p in company.products
        assert wh in company.warehouses
        assert inv in p.inventories
        assert mov in inv.movements
        assert mov.performer == user

    def test_product_model_has_no_warehouse_column(self):
        """Verify data model: Product should NOT have a warehouse_id column."""
        columns = [col.name for col in Product.__table__.columns]
        assert "warehouse_id" not in columns
