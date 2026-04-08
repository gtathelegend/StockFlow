"""
Tests for GET /api/companies/<company_id>/alerts/low-stock

Covers:
  - Happy path: alerts returned for low-stock products with recent sales
  - Threshold logic: reorder_level vs product-type defaults
  - Filtering: inactive products/warehouses excluded, no-sales excluded
  - Edge cases: no inventory, no supplier, company not found
  - Stockout estimation: days_until_stockout calculation
  - Pagination: limit/offset
  - Multi-warehouse: same product alerts per warehouse independently
  - Reserved stock: available = quantity - reserved_quantity
  - Query parameters: days, invalid params
"""

import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from flask import Flask
from sqlalchemy import event

from models import (
    db,
    Company,
    Warehouse,
    Product,
    Supplier,
    ProductSupplier,
    Inventory,
    InventoryMovement,
)
from alerts import alerts_bp


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

def _enable_sqlite_fk(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["TESTING"] = True
    db.init_app(app)
    app.register_blueprint(alerts_bp)
    with app.app_context():
        event.listen(db.engine, "connect", _enable_sqlite_fk)
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def company(app):
    with app.app_context():
        c = Company(name="Acme Corp")
        db.session.add(c)
        db.session.commit()
        return c.id


@pytest.fixture
def warehouse(app, company):
    with app.app_context():
        wh = Warehouse(company_id=company, name="Main Warehouse", location="NYC")
        db.session.add(wh)
        db.session.commit()
        return wh.id


@pytest.fixture
def supplier(app, company):
    with app.app_context():
        s = Supplier(
            company_id=company,
            name="Parts Corp",
            contact_email="orders@parts.com",
        )
        db.session.add(s)
        db.session.commit()
        return s.id


def _create_product(app, company, sku, name="Widget", price=10.00, product_type="normal"):
    with app.app_context():
        p = Product(
            company_id=company,
            name=name,
            sku=sku,
            price=Decimal(str(price)),
            product_type=product_type,
        )
        db.session.add(p)
        db.session.commit()
        return p.id


def _create_inventory(app, product_id, warehouse_id, quantity, reserved=0, reorder_level=None):
    with app.app_context():
        inv = Inventory(
            product_id=product_id,
            warehouse_id=warehouse_id,
            quantity=quantity,
            reserved_quantity=reserved,
            reorder_level=reorder_level,
        )
        db.session.add(inv)
        db.session.commit()
        return inv.id


def _create_sale_movement(app, inventory_id, quantity_sold, days_ago=5):
    """Create a sale movement (negative quantity_change) at a given time."""
    with app.app_context():
        inv = db.session.get(Inventory, inventory_id)
        mov = InventoryMovement(
            inventory_id=inventory_id,
            change_type="sale",
            quantity_change=-quantity_sold,
            quantity_before=inv.quantity + quantity_sold,
            quantity_after=inv.quantity,
            created_at=datetime.utcnow() - timedelta(days=days_ago),
        )
        db.session.add(mov)
        db.session.commit()


def _link_supplier(app, product_id, supplier_id, is_primary=True):
    with app.app_context():
        ps = ProductSupplier(
            product_id=product_id,
            supplier_id=supplier_id,
            is_primary=is_primary,
            lead_time_days=7,
            cost_price=Decimal("5.00"),
        )
        db.session.add(ps)
        db.session.commit()


def _url(company_id, **params):
    base = f"/api/companies/{company_id}/alerts/low-stock"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{base}?{qs}"
    return base


# ──────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────

class TestHappyPath:

    def test_basic_low_stock_alert(self, app, client, company, warehouse, supplier):
        """Product with stock below default threshold and recent sales -> alert."""
        pid = _create_product(app, company, "WDG-001")
        inv_id = _create_inventory(app, pid, warehouse, quantity=5)
        _create_sale_movement(app, inv_id, quantity_sold=10, days_ago=5)
        _link_supplier(app, pid, supplier)

        resp = client.get(_url(company))
        assert resp.status_code == 200
        body = resp.get_json()

        assert body["total_alerts"] == 1
        alert = body["alerts"][0]
        assert alert["product_id"] == pid
        assert alert["product_name"] == "Widget"
        assert alert["sku"] == "WDG-001"
        assert alert["warehouse_id"] == warehouse
        assert alert["warehouse_name"] == "Main Warehouse"
        assert alert["current_stock"] == 5  # quantity - reserved (5 - 0)
        assert alert["threshold"] == 20  # default for 'normal'
        assert alert["supplier"]["name"] == "Parts Corp"
        assert alert["supplier"]["contact_email"] == "orders@parts.com"
        assert alert["days_until_stockout"] is not None

    def test_response_includes_pagination_fields(self, app, client, company, warehouse):
        pid = _create_product(app, company, "WDG-001")
        inv_id = _create_inventory(app, pid, warehouse, quantity=5)
        _create_sale_movement(app, inv_id, 10)

        resp = client.get(_url(company))
        body = resp.get_json()
        assert "limit" in body
        assert "offset" in body
        assert "total_alerts" in body


# ──────────────────────────────────────────────
# Threshold logic
# ──────────────────────────────────────────────

class TestThresholdLogic:

    def test_reorder_level_overrides_default(self, app, client, company, warehouse):
        """When inventory.reorder_level is set, it takes priority over product-type default."""
        pid = _create_product(app, company, "WDG-001")
        # Stock=5, reorder_level=10 -> alert (5 < 10)
        inv_id = _create_inventory(app, pid, warehouse, quantity=5, reorder_level=10)
        _create_sale_movement(app, inv_id, 10)

        resp = client.get(_url(company))
        body = resp.get_json()
        assert body["total_alerts"] == 1
        assert body["alerts"][0]["threshold"] == 10

    def test_stock_above_reorder_level_no_alert(self, app, client, company, warehouse):
        """Stock at or above reorder_level -> no alert."""
        pid = _create_product(app, company, "WDG-001")
        # Stock=25, reorder_level=10 -> no alert (25 >= 10)
        inv_id = _create_inventory(app, pid, warehouse, quantity=25, reorder_level=10)
        _create_sale_movement(app, inv_id, 10)

        resp = client.get(_url(company))
        body = resp.get_json()
        assert body["total_alerts"] == 0

    def test_stock_above_default_threshold_no_alert(self, app, client, company, warehouse):
        """Stock above default threshold (20 for normal) -> no alert."""
        pid = _create_product(app, company, "WDG-001")
        # Stock=25, no reorder_level -> default 20 -> no alert (25 >= 20)
        inv_id = _create_inventory(app, pid, warehouse, quantity=25)
        _create_sale_movement(app, inv_id, 10)

        resp = client.get(_url(company))
        body = resp.get_json()
        assert body["total_alerts"] == 0

    def test_bundle_product_type_threshold(self, app, client, company, warehouse):
        """Bundle products use a different default threshold (15)."""
        pid = _create_product(app, company, "BND-001", product_type="bundle")
        # Stock=10, default for bundle=15 -> alert (10 < 15)
        inv_id = _create_inventory(app, pid, warehouse, quantity=10)
        _create_sale_movement(app, inv_id, 5)

        resp = client.get(_url(company))
        body = resp.get_json()
        assert body["total_alerts"] == 1
        assert body["alerts"][0]["threshold"] == 15


# ──────────────────────────────────────────────
# Filtering
# ──────────────────────────────────────────────

class TestFiltering:

    def test_no_recent_sales_excluded(self, app, client, company, warehouse):
        """Products with zero sales in the lookback window are excluded."""
        pid = _create_product(app, company, "WDG-001")
        _create_inventory(app, pid, warehouse, quantity=5)
        # No sale movements at all

        resp = client.get(_url(company))
        body = resp.get_json()
        assert body["total_alerts"] == 0

    def test_old_sales_excluded(self, app, client, company, warehouse):
        """Sales older than the lookback window don't count."""
        pid = _create_product(app, company, "WDG-001")
        inv_id = _create_inventory(app, pid, warehouse, quantity=5)
        # Sale 60 days ago, default lookback is 30
        _create_sale_movement(app, inv_id, quantity_sold=10, days_ago=60)

        resp = client.get(_url(company))
        body = resp.get_json()
        assert body["total_alerts"] == 0

    def test_inactive_product_excluded(self, app, client, company, warehouse):
        """Inactive products are filtered out."""
        pid = _create_product(app, company, "WDG-001")
        inv_id = _create_inventory(app, pid, warehouse, quantity=5)
        _create_sale_movement(app, inv_id, 10)

        with app.app_context():
            p = db.session.get(Product, pid)
            p.is_active = False
            db.session.commit()

        resp = client.get(_url(company))
        body = resp.get_json()
        assert body["total_alerts"] == 0

    def test_inactive_warehouse_excluded(self, app, client, company):
        """Inactive warehouses are filtered out."""
        with app.app_context():
            wh = Warehouse(company_id=company, name="Closed WH", is_active=False)
            db.session.add(wh)
            db.session.commit()
            wh_id = wh.id

        pid = _create_product(app, company, "WDG-001")
        inv_id = _create_inventory(app, pid, wh_id, quantity=5)
        _create_sale_movement(app, inv_id, 10)

        resp = client.get(_url(company))
        body = resp.get_json()
        assert body["total_alerts"] == 0

    def test_other_company_data_not_leaked(self, app, client, company, warehouse):
        """Alerts only include data from the requested company."""
        # Product in company 1
        pid1 = _create_product(app, company, "WDG-001")
        inv_id1 = _create_inventory(app, pid1, warehouse, quantity=5)
        _create_sale_movement(app, inv_id1, 10)

        # Create a second company with its own low-stock product
        with app.app_context():
            c2 = Company(name="Other Corp")
            db.session.add(c2)
            db.session.commit()
            wh2 = Warehouse(company_id=c2.id, name="Other WH")
            db.session.add(wh2)
            db.session.commit()
            p2 = Product(company_id=c2.id, name="Gizmo", sku="GZM-001", price=Decimal("5.00"))
            db.session.add(p2)
            db.session.commit()
            inv2 = Inventory(product_id=p2.id, warehouse_id=wh2.id, quantity=1)
            db.session.add(inv2)
            db.session.commit()
            mov2 = InventoryMovement(
                inventory_id=inv2.id, change_type="sale",
                quantity_change=-5, quantity_before=6, quantity_after=1,
                created_at=datetime.utcnow() - timedelta(days=2),
            )
            db.session.add(mov2)
            db.session.commit()

        # Request for company 1 should only return company 1's alerts
        resp = client.get(_url(company))
        body = resp.get_json()
        assert body["total_alerts"] == 1
        assert body["alerts"][0]["sku"] == "WDG-001"


# ──────────────────────────────────────────────
# Reserved stock
# ──────────────────────────────────────────────

class TestReservedStock:

    def test_reserved_quantity_reduces_available(self, app, client, company, warehouse):
        """Available stock = quantity - reserved. Alert triggers on available, not total."""
        pid = _create_product(app, company, "WDG-001")
        # quantity=25, reserved=10 -> available=15 -> below default 20 -> alert
        inv_id = _create_inventory(app, pid, warehouse, quantity=25, reserved=10)
        _create_sale_movement(app, inv_id, 10)

        resp = client.get(_url(company))
        body = resp.get_json()
        assert body["total_alerts"] == 1
        assert body["alerts"][0]["current_stock"] == 15  # 25 - 10

    def test_no_alert_when_reserved_doesnt_breach_threshold(self, app, client, company, warehouse):
        """quantity=30, reserved=5 -> available=25 -> above default 20 -> no alert."""
        pid = _create_product(app, company, "WDG-001")
        inv_id = _create_inventory(app, pid, warehouse, quantity=30, reserved=5)
        _create_sale_movement(app, inv_id, 10)

        resp = client.get(_url(company))
        body = resp.get_json()
        assert body["total_alerts"] == 0


# ──────────────────────────────────────────────
# Stockout estimation
# ──────────────────────────────────────────────

class TestStockoutEstimation:

    def test_days_until_stockout_calculation(self, app, client, company, warehouse):
        """days_until_stockout = current_stock / (total_sold / days)"""
        pid = _create_product(app, company, "WDG-001")
        # Stock=10, sold 30 units in 30 days -> avg 1/day -> stockout in 10 days
        inv_id = _create_inventory(app, pid, warehouse, quantity=10)
        _create_sale_movement(app, inv_id, quantity_sold=30, days_ago=15)

        resp = client.get(_url(company))
        body = resp.get_json()
        assert body["total_alerts"] == 1
        assert body["alerts"][0]["days_until_stockout"] == 10.0  # 10 / (30/30)

    def test_high_sales_rate_low_stockout(self, app, client, company, warehouse):
        """High sales rate -> few days until stockout."""
        pid = _create_product(app, company, "WDG-001")
        # Stock=5, sold 150 units in 30 days -> avg 5/day -> stockout in 1.0 day
        inv_id = _create_inventory(app, pid, warehouse, quantity=5)
        _create_sale_movement(app, inv_id, quantity_sold=150, days_ago=10)

        resp = client.get(_url(company))
        body = resp.get_json()
        assert body["total_alerts"] == 1
        assert body["alerts"][0]["days_until_stockout"] == 1.0  # 5 / (150/30)


# ──────────────────────────────────────────────
# Supplier info
# ──────────────────────────────────────────────

class TestSupplierInfo:

    def test_primary_supplier_included(self, app, client, company, warehouse, supplier):
        pid = _create_product(app, company, "WDG-001")
        inv_id = _create_inventory(app, pid, warehouse, quantity=5)
        _create_sale_movement(app, inv_id, 10)
        _link_supplier(app, pid, supplier, is_primary=True)

        resp = client.get(_url(company))
        body = resp.get_json()
        alert = body["alerts"][0]
        assert alert["supplier"] is not None
        assert alert["supplier"]["id"] == supplier
        assert alert["supplier"]["lead_time_days"] == 7
        assert alert["supplier"]["cost_price"] == 5.0

    def test_no_supplier_returns_null(self, app, client, company, warehouse):
        """Products without any supplier still appear, with supplier=null."""
        pid = _create_product(app, company, "WDG-001")
        inv_id = _create_inventory(app, pid, warehouse, quantity=5)
        _create_sale_movement(app, inv_id, 10)

        resp = client.get(_url(company))
        body = resp.get_json()
        assert body["total_alerts"] == 1
        assert body["alerts"][0]["supplier"] is None

    def test_fallback_to_non_primary_supplier(self, app, client, company, warehouse, supplier):
        """If no primary supplier, falls back to any active supplier."""
        pid = _create_product(app, company, "WDG-001")
        inv_id = _create_inventory(app, pid, warehouse, quantity=5)
        _create_sale_movement(app, inv_id, 10)
        _link_supplier(app, pid, supplier, is_primary=False)

        resp = client.get(_url(company))
        body = resp.get_json()
        assert body["alerts"][0]["supplier"] is not None
        assert body["alerts"][0]["supplier"]["id"] == supplier


# ──────────────────────────────────────────────
# Multi-warehouse
# ──────────────────────────────────────────────

class TestMultiWarehouse:

    def test_same_product_alert_per_warehouse(self, app, client, company):
        """Product low in two warehouses -> two separate alerts."""
        with app.app_context():
            wh1 = Warehouse(company_id=company, name="East", location="NYC")
            wh2 = Warehouse(company_id=company, name="West", location="LA")
            db.session.add_all([wh1, wh2])
            db.session.commit()
            wh1_id, wh2_id = wh1.id, wh2.id

        pid = _create_product(app, company, "WDG-001")
        inv1 = _create_inventory(app, pid, wh1_id, quantity=5)
        inv2 = _create_inventory(app, pid, wh2_id, quantity=3)
        _create_sale_movement(app, inv1, 10)
        _create_sale_movement(app, inv2, 8)

        resp = client.get(_url(company))
        body = resp.get_json()
        assert body["total_alerts"] == 2

        warehouse_ids = {a["warehouse_id"] for a in body["alerts"]}
        assert warehouse_ids == {wh1_id, wh2_id}

    def test_alert_only_for_low_warehouse(self, app, client, company):
        """Same product: low in one warehouse, fine in another -> one alert."""
        with app.app_context():
            wh1 = Warehouse(company_id=company, name="Low WH")
            wh2 = Warehouse(company_id=company, name="Full WH")
            db.session.add_all([wh1, wh2])
            db.session.commit()
            wh1_id, wh2_id = wh1.id, wh2.id

        pid = _create_product(app, company, "WDG-001")
        inv1 = _create_inventory(app, pid, wh1_id, quantity=5)
        inv2 = _create_inventory(app, pid, wh2_id, quantity=100)
        _create_sale_movement(app, inv1, 10)
        _create_sale_movement(app, inv2, 10)

        resp = client.get(_url(company))
        body = resp.get_json()
        assert body["total_alerts"] == 1
        assert body["alerts"][0]["warehouse_id"] == wh1_id


# ──────────────────────────────────────────────
# Sorting
# ──────────────────────────────────────────────

class TestSorting:

    def test_alerts_sorted_by_urgency(self, app, client, company, warehouse):
        """Most urgent (lowest days_until_stockout) comes first."""
        # Product A: stock=2, sold=30 -> avg 1/day -> 2.0 days (more urgent)
        pid_a = _create_product(app, company, "URGENT", name="Urgent")
        inv_a = _create_inventory(app, pid_a, warehouse, quantity=2)
        _create_sale_movement(app, inv_a, 30)

        # Product B: stock=15, sold=30 -> avg 1/day -> 15.0 days (less urgent)
        pid_b = _create_product(app, company, "CHILL", name="Chill")
        inv_b = _create_inventory(app, pid_b, warehouse, quantity=15)
        _create_sale_movement(app, inv_b, 30)

        resp = client.get(_url(company))
        body = resp.get_json()
        assert body["total_alerts"] == 2
        assert body["alerts"][0]["sku"] == "URGENT"
        assert body["alerts"][1]["sku"] == "CHILL"


# ──────────────────────────────────────────────
# Pagination
# ──────────────────────────────────────────────

class TestPagination:

    def _seed_many_alerts(self, app, company, warehouse, count):
        for i in range(count):
            pid = _create_product(app, company, f"P-{i:03d}", name=f"Product {i}")
            inv_id = _create_inventory(app, pid, warehouse, quantity=5)
            _create_sale_movement(app, inv_id, 10)

    def test_default_limit(self, app, client, company, warehouse):
        self._seed_many_alerts(app, company, warehouse, 3)
        resp = client.get(_url(company))
        body = resp.get_json()
        assert body["total_alerts"] == 3
        assert len(body["alerts"]) == 3

    def test_limit_parameter(self, app, client, company, warehouse):
        self._seed_many_alerts(app, company, warehouse, 5)
        resp = client.get(_url(company, limit=2))
        body = resp.get_json()
        assert body["total_alerts"] == 5
        assert len(body["alerts"]) == 2

    def test_offset_parameter(self, app, client, company, warehouse):
        self._seed_many_alerts(app, company, warehouse, 5)
        resp = client.get(_url(company, limit=2, offset=2))
        body = resp.get_json()
        assert body["total_alerts"] == 5
        assert len(body["alerts"]) == 2

    def test_offset_beyond_total(self, app, client, company, warehouse):
        self._seed_many_alerts(app, company, warehouse, 3)
        resp = client.get(_url(company, limit=10, offset=100))
        body = resp.get_json()
        assert body["total_alerts"] == 3
        assert len(body["alerts"]) == 0


# ──────────────────────────────────────────────
# Custom lookback window
# ──────────────────────────────────────────────

class TestLookbackDays:

    def test_custom_days_parameter(self, app, client, company, warehouse):
        """Sales 15 days ago should count with days=20 but not days=10."""
        pid = _create_product(app, company, "WDG-001")
        inv_id = _create_inventory(app, pid, warehouse, quantity=5)
        _create_sale_movement(app, inv_id, quantity_sold=10, days_ago=15)

        # 20-day window includes the 15-day-old sale
        resp = client.get(_url(company, days=20))
        assert resp.get_json()["total_alerts"] == 1

        # 10-day window excludes it
        resp = client.get(_url(company, days=10))
        assert resp.get_json()["total_alerts"] == 0


# ──────────────────────────────────────────────
# Error handling
# ──────────────────────────────────────────────

class TestErrorHandling:

    def test_company_not_found(self, client):
        resp = client.get(_url(99999))
        assert resp.status_code == 404
        assert "Company not found" in resp.get_json()["error"]

    def test_invalid_days_parameter(self, client, company):
        resp = client.get(_url(company, days="abc"))
        assert resp.status_code == 400

    def test_negative_days_parameter(self, client, company):
        resp = client.get(_url(company, days=-1))
        assert resp.status_code == 400

    def test_zero_limit(self, client, company):
        resp = client.get(_url(company, limit=0))
        assert resp.status_code == 400

    def test_negative_offset(self, client, company):
        resp = client.get(_url(company, offset=-1))
        assert resp.status_code == 400

    def test_empty_company_returns_empty_alerts(self, app, client, company):
        """Company with no inventory returns empty list, not an error."""
        resp = client.get(_url(company))
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["alerts"] == []
        assert body["total_alerts"] == 0
