"""
Original buggy code provided by the previous intern.
This file is kept for reference only - DO NOT use in production.
See routes.py for the corrected implementation.
"""

from flask import request
from models import db, Product, Inventory


@app.route("/api/products", methods=["POST"])
def create_product():
    data = request.json

    # Create new product
    product = Product(
        name=data["name"],
        sku=data["sku"],
        price=data["price"],
        warehouse_id=data["warehouse_id"],
    )

    db.session.add(product)
    db.session.commit()

    # Update inventory count
    inventory = Inventory(
        product_id=product.id,
        warehouse_id=data["warehouse_id"],
        quantity=data["initial_quantity"],
    )

    db.session.add(inventory)
    db.session.commit()

    return {"message": "Product created", "product_id": product.id}
