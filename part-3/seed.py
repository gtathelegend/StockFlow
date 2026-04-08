"""
Seed script to populate the database with test data for Postman testing.
Run: python seed.py
"""

from datetime import datetime, timedelta
from decimal import Decimal

from app import create_app
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


def seed():
    app = create_app()

    with app.app_context():
        # Clear existing data
        db.drop_all()
        db.create_all()

        # ── Company 1: Acme Corp (main test company) ──
        acme = Company(name="Acme Corp")
        db.session.add(acme)
        db.session.commit()

        # ── Company 2: Other Corp (for cross-tenant isolation testing) ──
        other = Company(name="Other Corp")
        db.session.add(other)
        db.session.commit()

        # ── Warehouses ──
        wh_east = Warehouse(company_id=acme.id, name="East Warehouse", location="New York")
        wh_west = Warehouse(company_id=acme.id, name="West Warehouse", location="Los Angeles")
        wh_closed = Warehouse(company_id=acme.id, name="Closed Warehouse", location="Chicago", is_active=False)
        wh_other = Warehouse(company_id=other.id, name="Other WH", location="Seattle")
        db.session.add_all([wh_east, wh_west, wh_closed, wh_other])
        db.session.commit()

        # ── Suppliers ──
        sup_parts = Supplier(company_id=acme.id, name="Parts Corp", contact_email="orders@parts.com")
        sup_global = Supplier(company_id=acme.id, name="Global Supply", contact_email="info@globalsupply.com")
        db.session.add_all([sup_parts, sup_global])
        db.session.commit()

        # ── Products ──
        # Product 1: Low stock, recent sales, has primary supplier  →  ALERT
        p_widget = Product(company_id=acme.id, name="Widget A", sku="WID-001", price=Decimal("19.99"))
        # Product 2: Low stock, recent sales, NO supplier           →  ALERT (supplier=null)
        p_gadget = Product(company_id=acme.id, name="Gadget B", sku="GDG-002", price=Decimal("49.99"))
        # Product 3: Stock ABOVE threshold, recent sales            →  NO ALERT
        p_bolt = Product(company_id=acme.id, name="Bolt C", sku="BLT-003", price=Decimal("1.50"))
        # Product 4: Low stock, but NO recent sales                 →  NO ALERT
        p_stale = Product(company_id=acme.id, name="Stale Item D", sku="STL-004", price=Decimal("5.00"))
        # Product 5: Inactive product, low stock, recent sales      →  NO ALERT
        p_disco = Product(company_id=acme.id, name="Discontinued E", sku="DIS-005", price=Decimal("9.99"), is_active=False)
        # Product 6: Bundle type, low stock, recent sales           →  ALERT (threshold=15)
        p_bundle = Product(company_id=acme.id, name="Bundle F", sku="BND-006", price=Decimal("99.99"), product_type="bundle")
        # Product 7: Low stock in BOTH warehouses                   →  2 ALERTS
        p_multi = Product(company_id=acme.id, name="Multi-WH G", sku="MWH-007", price=Decimal("14.99"))
        # Product 8: Custom reorder_level, stock between default and custom  →  test threshold override
        p_custom = Product(company_id=acme.id, name="Custom Thresh H", sku="CTH-008", price=Decimal("29.99"))
        # Product 9: High reserved qty makes available stock low    →  ALERT
        p_reserved = Product(company_id=acme.id, name="Reserved Stock I", sku="RSV-009", price=Decimal("39.99"))
        # Product 10: Other company's product (should NOT appear)
        p_other = Product(company_id=other.id, name="Other Product", sku="OTH-001", price=Decimal("10.00"))

        db.session.add_all([p_widget, p_gadget, p_bolt, p_stale, p_disco, p_bundle, p_multi, p_custom, p_reserved, p_other])
        db.session.commit()

        # ── Supplier links ──
        db.session.add(ProductSupplier(product_id=p_widget.id, supplier_id=sup_parts.id, is_primary=True, lead_time_days=7, cost_price=Decimal("8.00")))
        db.session.add(ProductSupplier(product_id=p_widget.id, supplier_id=sup_global.id, is_primary=False, lead_time_days=14, cost_price=Decimal("7.50")))
        db.session.add(ProductSupplier(product_id=p_bundle.id, supplier_id=sup_global.id, is_primary=True, lead_time_days=10, cost_price=Decimal("60.00")))
        db.session.add(ProductSupplier(product_id=p_multi.id, supplier_id=sup_parts.id, is_primary=True, lead_time_days=5, cost_price=Decimal("6.00")))
        db.session.add(ProductSupplier(product_id=p_reserved.id, supplier_id=sup_parts.id, is_primary=True, lead_time_days=3, cost_price=Decimal("20.00")))
        # p_gadget has NO supplier (intentional)
        db.session.commit()

        now = datetime.utcnow()

        # ── Inventory + Movements ──

        def add_inv(product, warehouse, qty, reserved=0, reorder_level=None):
            inv = Inventory(
                product_id=product.id,
                warehouse_id=warehouse.id,
                quantity=qty,
                reserved_quantity=reserved,
                reorder_level=reorder_level,
            )
            db.session.add(inv)
            db.session.commit()
            return inv

        def add_sale(inv, sold, days_ago):
            mov = InventoryMovement(
                inventory_id=inv.id,
                change_type="sale",
                quantity_change=-sold,
                quantity_before=inv.quantity + sold,
                quantity_after=inv.quantity,
                created_at=now - timedelta(days=days_ago),
            )
            db.session.add(mov)
            db.session.commit()

        # 1. Widget A: stock=5, sold 30 in last 10 days → alert, ~5 days to stockout
        inv1 = add_inv(p_widget, wh_east, qty=5)
        add_sale(inv1, sold=30, days_ago=10)

        # 2. Gadget B: stock=3, sold 15 in last 5 days → alert, no supplier
        inv2 = add_inv(p_gadget, wh_east, qty=3)
        add_sale(inv2, sold=15, days_ago=5)

        # 3. Bolt C: stock=100, sold 20 in last 7 days → NO alert (above threshold)
        inv3 = add_inv(p_bolt, wh_east, qty=100)
        add_sale(inv3, sold=20, days_ago=7)

        # 4. Stale Item D: stock=2, NO sales → NO alert
        add_inv(p_stale, wh_east, qty=2)

        # 5. Discontinued E: stock=1, sold 5 in last 3 days → NO alert (inactive)
        inv5 = add_inv(p_disco, wh_east, qty=1)
        add_sale(inv5, sold=5, days_ago=3)

        # 6. Bundle F: stock=10, sold 20 in last 15 days → alert (threshold=15)
        inv6 = add_inv(p_bundle, wh_west, qty=10)
        add_sale(inv6, sold=20, days_ago=15)

        # 7. Multi-WH G: low in BOTH warehouses
        inv7a = add_inv(p_multi, wh_east, qty=8)
        add_sale(inv7a, sold=25, days_ago=12)
        inv7b = add_inv(p_multi, wh_west, qty=4)
        add_sale(inv7b, sold=18, days_ago=8)

        # 8. Custom Thresh H: stock=18, reorder_level=25 → alert (18 < 25)
        #    Without custom level, default is 20, and 18 < 20 would also alert
        #    But set reorder_level=25 to show override
        inv8 = add_inv(p_custom, wh_east, qty=18, reorder_level=25)
        add_sale(inv8, sold=10, days_ago=20)

        # 9. Reserved Stock I: qty=30, reserved=20 → available=10 → alert (10 < 20)
        inv9 = add_inv(p_reserved, wh_east, qty=30, reserved=20)
        add_sale(inv9, sold=40, days_ago=14)

        # 10. Other company product: stock=1, recent sales → should NOT appear for Acme
        inv10 = add_inv(p_other, wh_other, qty=1)
        add_sale(inv10, sold=10, days_ago=3)

        # 11. Widget in closed warehouse: stock=2, recent sales → NO alert (inactive WH)
        inv11 = add_inv(p_widget, wh_closed, qty=2)
        add_sale(inv11, sold=5, days_ago=2)

        print("=" * 60)
        print("Seed data created successfully!")
        print("=" * 60)
        print()
        print(f"  Company 1 (Acme Corp):  id={acme.id}")
        print(f"  Company 2 (Other Corp): id={other.id}")
        print()
        print("  Warehouses:")
        print(f"    East Warehouse (active):   id={wh_east.id}")
        print(f"    West Warehouse (active):   id={wh_west.id}")
        print(f"    Closed Warehouse (inactive): id={wh_closed.id}")
        print()
        print("  Expected alerts for Acme (company_id=1):")
        print("    1. Widget A      (WID-001) - East WH  - stock=5,  threshold=20")
        print("    2. Gadget B      (GDG-002) - East WH  - stock=3,  threshold=20, NO supplier")
        print("    3. Bundle F      (BND-006) - West WH  - stock=10, threshold=15")
        print("    4. Multi-WH G    (MWH-007) - East WH  - stock=8,  threshold=20")
        print("    5. Multi-WH G    (MWH-007) - West WH  - stock=4,  threshold=20")
        print("    6. Custom Thresh (CTH-008) - East WH  - stock=18, threshold=25 (custom)")
        print("    7. Reserved I    (RSV-009) - East WH  - avail=10, threshold=20")
        print()
        print("  NOT expected (filtered out):")
        print("    - Bolt C       (stock=100, above threshold)")
        print("    - Stale Item D (no recent sales)")
        print("    - Discontinued E (is_active=False)")
        print("    - Widget A in Closed WH (warehouse is_active=False)")
        print("    - Other Corp's product (different company)")
        print()
        print("  Test URL: http://127.0.0.1:5001/api/companies/1/alerts/low-stock")
        print("=" * 60)


if __name__ == "__main__":
    seed()
