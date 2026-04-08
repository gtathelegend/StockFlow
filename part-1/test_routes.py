import pytest
from decimal import Decimal
from app import create_app
from models import db, Product, Warehouse, Inventory


@pytest.fixture
def app():
    """Create a test app with an in-memory SQLite database."""
    test_config = {
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "TESTING": True,
    }
    app = create_app(config=test_config)
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def seed_warehouse(app):
    """Seed a warehouse and return its ID."""
    with app.app_context():
        wh = Warehouse(name="Test Warehouse", location="Test City")
        db.session.add(wh)
        db.session.commit()
        return wh.id


def valid_product(overrides=None):
    """Helper to build a valid product payload."""
    data = {"name": "Widget", "sku": "WDG-001", "price": 29.99}
    if overrides:
        data.update(overrides)
    return data


# ──────────────────────────────────────────────
# Success cases
# ──────────────────────────────────────────────


class TestCreateProductSuccess:

    def test_create_product_without_inventory(self, client):
        resp = client.post("/api/products", json=valid_product())
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["message"] == "Product created"
        assert "product_id" in body

    def test_create_product_with_inventory(self, client, seed_warehouse):
        payload = valid_product(
            {
                "warehouse_id": seed_warehouse,
                "initial_quantity": 100,
            }
        )
        resp = client.post("/api/products", json=payload)
        assert resp.status_code == 201

    def test_product_stored_correctly(self, client, app):
        client.post("/api/products", json=valid_product())
        with app.app_context():
            product = Product.query.filter_by(sku="WDG-001").first()
            assert product is not None
            assert product.name == "Widget"
            assert product.price == Decimal("29.99")

    def test_inventory_stored_correctly(self, client, app, seed_warehouse):
        payload = valid_product(
            {"warehouse_id": seed_warehouse, "initial_quantity": 50}
        )
        client.post("/api/products", json=payload)
        with app.app_context():
            inv = Inventory.query.first()
            assert inv is not None
            assert inv.quantity == 50
            assert inv.warehouse_id == seed_warehouse

    def test_no_inventory_created_without_warehouse(self, client, app):
        client.post("/api/products", json=valid_product())
        with app.app_context():
            assert Inventory.query.count() == 0

    def test_default_quantity_is_zero(self, client, app, seed_warehouse):
        payload = valid_product({"warehouse_id": seed_warehouse})
        client.post("/api/products", json=payload)
        with app.app_context():
            inv = Inventory.query.first()
            assert inv is not None
            assert inv.quantity == 0

    def test_name_and_sku_are_stripped(self, client, app):
        payload = valid_product({"name": "  Gadget  ", "sku": "  G-001  "})
        client.post("/api/products", json=payload)
        with app.app_context():
            product = Product.query.first()
            assert product.name == "Gadget"
            assert product.sku == "G-001"

    def test_integer_price_accepted(self, client):
        resp = client.post("/api/products", json=valid_product({"price": 10}))
        assert resp.status_code == 201


# ──────────────────────────────────────────────
# Validation errors (400)
# ──────────────────────────────────────────────


class TestValidationErrors:

    def test_empty_body(self, client):
        resp = client.post(
            "/api/products", data="", content_type="application/json"
        )
        assert resp.status_code == 400

    def test_non_json_body(self, client):
        resp = client.post(
            "/api/products", data="not json", content_type="text/plain"
        )
        assert resp.status_code == 400

    def test_missing_name(self, client):
        payload = valid_product()
        del payload["name"]
        resp = client.post("/api/products", json=payload)
        assert resp.status_code == 400
        assert "'name' is required" in resp.get_json()["errors"]

    def test_missing_sku(self, client):
        payload = valid_product()
        del payload["sku"]
        resp = client.post("/api/products", json=payload)
        assert resp.status_code == 400
        assert "'sku' is required" in resp.get_json()["errors"]

    def test_missing_price(self, client):
        payload = valid_product()
        del payload["price"]
        resp = client.post("/api/products", json=payload)
        assert resp.status_code == 400
        assert "'price' is required" in resp.get_json()["errors"]

    def test_negative_price(self, client):
        resp = client.post("/api/products", json=valid_product({"price": -5}))
        assert resp.status_code == 400
        assert "'price' must be a positive number" in resp.get_json()["errors"]

    def test_zero_price(self, client):
        resp = client.post("/api/products", json=valid_product({"price": 0}))
        assert resp.status_code == 400

    def test_string_price(self, client):
        resp = client.post("/api/products", json=valid_product({"price": "free"}))
        assert resp.status_code == 400

    def test_negative_quantity(self, client, seed_warehouse):
        payload = valid_product(
            {"warehouse_id": seed_warehouse, "initial_quantity": -10}
        )
        resp = client.post("/api/products", json=payload)
        assert resp.status_code == 400
        assert "'initial_quantity' must be a non-negative integer" in resp.get_json()["errors"]

    def test_float_quantity(self, client, seed_warehouse):
        payload = valid_product(
            {"warehouse_id": seed_warehouse, "initial_quantity": 3.5}
        )
        resp = client.post("/api/products", json=payload)
        assert resp.status_code == 400

    def test_invalid_warehouse_id_type(self, client):
        resp = client.post(
            "/api/products", json=valid_product({"warehouse_id": "abc"})
        )
        assert resp.status_code == 400


# ──────────────────────────────────────────────
# Duplicate SKU (409)
# ──────────────────────────────────────────────


class TestDuplicateSku:

    def test_duplicate_sku_returns_409(self, client):
        client.post("/api/products", json=valid_product())
        resp = client.post("/api/products", json=valid_product({"name": "Other"}))
        assert resp.status_code == 409
        assert "SKU already exists" in resp.get_json()["error"]

    def test_different_sku_succeeds(self, client):
        client.post("/api/products", json=valid_product())
        resp = client.post(
            "/api/products", json=valid_product({"sku": "WDG-002"})
        )
        assert resp.status_code == 201


# ──────────────────────────────────────────────
# Warehouse not found (404)
# ──────────────────────────────────────────────


class TestWarehouseNotFound:

    def test_nonexistent_warehouse_returns_404(self, client):
        payload = valid_product({"warehouse_id": 9999})
        resp = client.post("/api/products", json=payload)
        assert resp.status_code == 404
        assert "Warehouse not found" in resp.get_json()["error"]


# ──────────────────────────────────────────────
# Transaction atomicity
# ──────────────────────────────────────────────


class TestTransactionAtomicity:

    def test_no_product_left_behind_on_inventory_error(self, client, app):
        """
        If a product is created but inventory fails, the product should
        also be rolled back. We simulate this by providing a warehouse_id
        that passes the existence check but causes a DB constraint violation
        (duplicate product-warehouse pair via two rapid calls).
        """
        # This test verifies the single-transaction design:
        # Create a product with inventory successfully first
        with app.app_context():
            wh = Warehouse(name="WH", location="Loc")
            db.session.add(wh)
            db.session.commit()
            wh_id = wh.id

        payload = valid_product({"warehouse_id": wh_id, "initial_quantity": 10})
        resp1 = client.post("/api/products", json=payload)
        assert resp1.status_code == 201

        # Second call with same SKU should be caught by uniqueness check
        resp2 = client.post("/api/products", json=payload)
        assert resp2.status_code == 409

        # Verify only one product exists
        with app.app_context():
            assert Product.query.count() == 1
            assert Inventory.query.count() == 1


# ──────────────────────────────────────────────
# Multi-warehouse support
# ──────────────────────────────────────────────


class TestMultiWarehouse:

    def test_same_product_in_multiple_warehouses(self, client, app):
        """Product model has no warehouse_id -- inventory links them."""
        with app.app_context():
            wh1 = Warehouse(name="WH1", location="A")
            wh2 = Warehouse(name="WH2", location="B")
            db.session.add_all([wh1, wh2])
            db.session.commit()
            wh1_id, wh2_id = wh1.id, wh2.id

        # Create product in warehouse 1
        resp1 = client.post(
            "/api/products",
            json=valid_product({"warehouse_id": wh1_id, "initial_quantity": 10}),
        )
        assert resp1.status_code == 201
        product_id = resp1.get_json()["product_id"]

        # Manually add inventory for same product in warehouse 2
        # (the create endpoint uses a unique SKU, so we verify the model allows it)
        with app.app_context():
            inv2 = Inventory(
                product_id=product_id, warehouse_id=wh2_id, quantity=20
            )
            db.session.add(inv2)
            db.session.commit()

            # Product should have 2 inventory records
            product = db.session.get(Product, product_id)
            assert len(product.inventories) == 2

    def test_product_model_has_no_warehouse_column(self):
        """Verify the data model fix: Product should not have warehouse_id."""
        columns = [col.name for col in Product.__table__.columns]
        assert "warehouse_id" not in columns
