"""
Low-stock alerts endpoint.

GET /api/companies/<company_id>/alerts/low-stock

Returns products whose available stock (quantity - reserved_quantity) is below
their reorder threshold, filtered to only products with recent sales activity.

Query parameters:
  - days   : lookback window for "recent" sales (default: 30)
  - limit  : max alerts to return, for pagination (default: 50)
  - offset : pagination offset (default: 0)
"""

from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify
from sqlalchemy import func, case, literal

from models import (
    db,
    Company,
    Product,
    Warehouse,
    Supplier,
    ProductSupplier,
    Inventory,
    InventoryMovement,
)

alerts_bp = Blueprint("alerts", __name__)

# ──────────────────────────────────────────────
# Default thresholds by product type.
# Used only when inventory.reorder_level is NULL.
# In production this would live in a config table.
# ──────────────────────────────────────────────
DEFAULT_THRESHOLDS = {
    "normal": 20,
    "bundle": 15,
}
DEFAULT_THRESHOLD_FALLBACK = 20


def _get_default_threshold(product_type):
    return DEFAULT_THRESHOLDS.get(product_type, DEFAULT_THRESHOLD_FALLBACK)


@alerts_bp.route(
    "/api/companies/<int:company_id>/alerts/low-stock", methods=["GET"]
)
def get_low_stock_alerts(company_id):
    # ── 1. Validate company exists ────────────────────────
    company = db.session.get(Company, company_id)
    if not company:
        return jsonify({"error": "Company not found"}), 404

    # ── 2. Parse & validate query parameters ──────────────
    try:
        days = int(request.args.get("days", 30))
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid query parameters"}), 400

    if days < 1 or limit < 1 or offset < 0:
        return jsonify({"error": "days and limit must be >= 1, offset must be >= 0"}), 400

    recent_cutoff = datetime.utcnow() - timedelta(days=days)

    # ── 3. Build a subquery: total sale quantity per inventory row ─
    #
    # "Recent sales activity" = inventory_movements with change_type='sale'
    # in the last N days.  Sale movements have negative quantity_change,
    # so we use func.abs() to get the positive total units sold.
    #
    # This replaces the N+1 per-row query in the original solution.
    # ──────────────────────────────────────────────────────
    sales_subq = (
        db.session.query(
            InventoryMovement.inventory_id,
            func.abs(func.sum(InventoryMovement.quantity_change)).label("total_sold"),
        )
        .filter(
            InventoryMovement.change_type == "sale",
            InventoryMovement.created_at >= recent_cutoff,
        )
        .group_by(InventoryMovement.inventory_id)
        .subquery("recent_sales")
    )

    # ── 4. Build a subquery: primary supplier per product ─
    #
    # Picks one supplier per product: prefers is_primary=True, then lowest id.
    # Uses ROW_NUMBER() window function for portable SQL (works on SQLite + PG).
    # This replaces the N+1 per-row supplier lookup in the original solution.
    # ──────────────────────────────────────────────────────
    from sqlalchemy import over

    ranked_suppliers = (
        db.session.query(
            ProductSupplier.product_id,
            Supplier.id.label("supplier_id"),
            Supplier.name.label("supplier_name"),
            Supplier.contact_email.label("supplier_email"),
            ProductSupplier.lead_time_days,
            ProductSupplier.cost_price,
            func.row_number()
            .over(
                partition_by=ProductSupplier.product_id,
                order_by=[ProductSupplier.is_primary.desc(), Supplier.id.asc()],
            )
            .label("rn"),
        )
        .join(Supplier, ProductSupplier.supplier_id == Supplier.id)
        .filter(Supplier.is_active == True)
        .subquery("ranked_suppliers")
    )

    supplier_subq = (
        db.session.query(
            ranked_suppliers.c.product_id,
            ranked_suppliers.c.supplier_id,
            ranked_suppliers.c.supplier_name,
            ranked_suppliers.c.supplier_email,
            ranked_suppliers.c.lead_time_days,
            ranked_suppliers.c.cost_price,
        )
        .filter(ranked_suppliers.c.rn == 1)
        .subquery("primary_supplier")
    )

    # ── 5. Main query: join inventory + product + warehouse + sales + supplier
    #
    # Available stock = quantity - reserved_quantity
    # Threshold priority: inventory.reorder_level > default for product_type
    # Only include rows where available_stock < threshold AND total_sold > 0
    # ──────────────────────────────────────────────────────
    available_stock = (Inventory.quantity - Inventory.reserved_quantity).label(
        "available_stock"
    )

    query = (
        db.session.query(
            Product.id.label("product_id"),
            Product.name.label("product_name"),
            Product.sku,
            Product.product_type,
            Warehouse.id.label("warehouse_id"),
            Warehouse.name.label("warehouse_name"),
            available_stock,
            Inventory.reorder_level,
            sales_subq.c.total_sold,
            supplier_subq.c.supplier_id,
            supplier_subq.c.supplier_name,
            supplier_subq.c.supplier_email,
            supplier_subq.c.lead_time_days,
            supplier_subq.c.cost_price,
        )
        .join(Product, Inventory.product_id == Product.id)
        .join(Warehouse, Inventory.warehouse_id == Warehouse.id)
        # INNER join on sales: excludes products with zero recent sales
        .join(sales_subq, sales_subq.c.inventory_id == Inventory.id)
        # LEFT join on supplier: products without a supplier still appear
        .outerjoin(supplier_subq, supplier_subq.c.product_id == Product.id)
        .filter(
            # Scope to this company
            Product.company_id == company_id,
            # Only active products and warehouses
            Product.is_active == True,
            Warehouse.is_active == True,
        )
    )

    # ── 6. Execute and filter in Python for threshold logic ─
    #
    # SQLite doesn't support CASE with column-dependent defaults cleanly
    # across all ORMs, so we compute threshold + filter in Python.
    # In production PostgreSQL, this could be pushed into the query.
    # ──────────────────────────────────────────────────────
    raw_rows = query.all()

    alerts = []
    for row in raw_rows:
        # Threshold: use per-warehouse reorder_level if set, else product-type default
        threshold = (
            row.reorder_level
            if row.reorder_level is not None
            else _get_default_threshold(row.product_type)
        )

        # Skip if stock is at or above threshold
        if row.available_stock >= threshold:
            continue

        # Estimate days until stockout from average daily sales rate
        avg_daily_sales = row.total_sold / days
        if avg_daily_sales > 0:
            days_until_stockout = round(row.available_stock / avg_daily_sales, 1)
        else:
            # total_sold > 0 is guaranteed by the INNER JOIN, but guard anyway
            days_until_stockout = None

        supplier_data = None
        if row.supplier_id is not None:
            supplier_data = {
                "id": row.supplier_id,
                "name": row.supplier_name,
                "contact_email": row.supplier_email,
                "lead_time_days": row.lead_time_days,
                "cost_price": float(row.cost_price) if row.cost_price else None,
            }

        alerts.append(
            {
                "product_id": row.product_id,
                "product_name": row.product_name,
                "sku": row.sku,
                "warehouse_id": row.warehouse_id,
                "warehouse_name": row.warehouse_name,
                "current_stock": row.available_stock,
                "threshold": threshold,
                "days_until_stockout": days_until_stockout,
                "supplier": supplier_data,
            }
        )

    # ── 7. Sort by urgency: lowest days_until_stockout first ─
    alerts.sort(key=lambda a: (a["days_until_stockout"] is None, a["days_until_stockout"] or 0))

    # ── 8. Paginate ───────────────────────────────────────
    total_alerts = len(alerts)
    paginated = alerts[offset : offset + limit]

    return jsonify(
        {
            "alerts": paginated,
            "total_alerts": total_alerts,
            "limit": limit,
            "offset": offset,
        }
    ), 200
