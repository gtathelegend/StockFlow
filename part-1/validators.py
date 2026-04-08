from decimal import Decimal, InvalidOperation


def validate_product_data(data):
    """Validate incoming product creation data and return a list of errors."""
    errors = []

    if data is None:
        return ["Request body must be valid JSON"]

    # Required fields
    for field in ["name", "sku", "price"]:
        if field not in data or not str(data[field]).strip():
            errors.append(f"'{field}' is required")

    # Price validation
    if "price" in data and data["price"] is not None:
        try:
            price = Decimal(str(data["price"]))
            if price <= 0:
                errors.append("'price' must be a positive number")
        except (InvalidOperation, ValueError, TypeError):
            errors.append("'price' must be a valid decimal number")

    # warehouse_id validation (optional field)
    if "warehouse_id" in data and data["warehouse_id"] is not None:
        if not isinstance(data["warehouse_id"], int) or data["warehouse_id"] <= 0:
            errors.append("'warehouse_id' must be a positive integer")

    # initial_quantity validation (optional field)
    if "initial_quantity" in data and data["initial_quantity"] is not None:
        if not isinstance(data["initial_quantity"], int) or data["initial_quantity"] < 0:
            errors.append("'initial_quantity' must be a non-negative integer")

    return errors
