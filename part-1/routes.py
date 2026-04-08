from decimal import Decimal
from flask import Blueprint, request, jsonify
from sqlalchemy.exc import IntegrityError

from models import db, Product, Warehouse, Inventory
from validators import validate_product_data

products_bp = Blueprint("products", __name__)


@products_bp.route("/api/products", methods=["POST"])
def create_product():
    data = request.get_json(silent=True)

    # --- Input validation ---
    errors = validate_product_data(data)
    if errors:
        return jsonify({"errors": errors}), 400

    # --- SKU uniqueness check ---
    if Product.query.filter_by(sku=data["sku"].strip()).first():
        return jsonify({"error": "A product with this SKU already exists"}), 409

    # --- Warehouse existence check (if provided) ---
    if data.get("warehouse_id") is not None:
        warehouse = Warehouse.query.get(data["warehouse_id"])
        if not warehouse:
            return jsonify({"error": "Warehouse not found"}), 404

    # --- Create product + inventory in a single atomic transaction ---
    try:
        product = Product(
            name=data["name"].strip(),
            sku=data["sku"].strip(),
            price=Decimal(str(data["price"])),
        )
        db.session.add(product)
        db.session.flush()  # Get product.id without committing

        # Create inventory record only if warehouse is specified
        if data.get("warehouse_id") is not None:
            inventory = Inventory(
                product_id=product.id,
                warehouse_id=data["warehouse_id"],
                quantity=data.get("initial_quantity", 0),
            )
            db.session.add(inventory)

        db.session.commit()

    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Duplicate SKU or invalid foreign key reference"}), 409

    except Exception:
        db.session.rollback()
        return jsonify({"error": "Internal server error"}), 500

    return jsonify({"message": "Product created", "product_id": product.id}), 201
