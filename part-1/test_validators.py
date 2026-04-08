import pytest
from validators import validate_product_data


class TestValidateProductData:
    """Unit tests for the validate_product_data function."""

    # --- None / empty body ---

    def test_none_body(self):
        errors = validate_product_data(None)
        assert errors == ["Request body must be valid JSON"]

    def test_empty_dict(self):
        errors = validate_product_data({})
        assert "'name' is required" in errors
        assert "'sku' is required" in errors
        assert "'price' is required" in errors

    # --- Required fields ---

    def test_missing_name(self):
        errors = validate_product_data({"sku": "A1", "price": 10})
        assert "'name' is required" in errors

    def test_missing_sku(self):
        errors = validate_product_data({"name": "Widget", "price": 10})
        assert "'sku' is required" in errors

    def test_missing_price(self):
        errors = validate_product_data({"name": "Widget", "sku": "A1"})
        assert "'price' is required" in errors

    def test_blank_name(self):
        errors = validate_product_data({"name": "  ", "sku": "A1", "price": 10})
        assert "'name' is required" in errors

    def test_blank_sku(self):
        errors = validate_product_data({"name": "Widget", "sku": "  ", "price": 10})
        assert "'sku' is required" in errors

    # --- Price validation ---

    def test_valid_decimal_price(self):
        errors = validate_product_data({"name": "W", "sku": "A1", "price": 19.99})
        assert len(errors) == 0

    def test_valid_integer_price(self):
        errors = validate_product_data({"name": "W", "sku": "A1", "price": 10})
        assert len(errors) == 0

    def test_zero_price(self):
        errors = validate_product_data({"name": "W", "sku": "A1", "price": 0})
        assert "'price' must be a positive number" in errors

    def test_negative_price(self):
        errors = validate_product_data({"name": "W", "sku": "A1", "price": -5})
        assert "'price' must be a positive number" in errors

    def test_non_numeric_price(self):
        errors = validate_product_data({"name": "W", "sku": "A1", "price": "abc"})
        assert "'price' must be a valid decimal number" in errors

    # --- warehouse_id validation ---

    def test_valid_warehouse_id(self):
        errors = validate_product_data(
            {"name": "W", "sku": "A1", "price": 10, "warehouse_id": 1}
        )
        assert len(errors) == 0

    def test_zero_warehouse_id(self):
        errors = validate_product_data(
            {"name": "W", "sku": "A1", "price": 10, "warehouse_id": 0}
        )
        assert "'warehouse_id' must be a positive integer" in errors

    def test_negative_warehouse_id(self):
        errors = validate_product_data(
            {"name": "W", "sku": "A1", "price": 10, "warehouse_id": -1}
        )
        assert "'warehouse_id' must be a positive integer" in errors

    def test_string_warehouse_id(self):
        errors = validate_product_data(
            {"name": "W", "sku": "A1", "price": 10, "warehouse_id": "abc"}
        )
        assert "'warehouse_id' must be a positive integer" in errors

    def test_none_warehouse_id_is_ignored(self):
        errors = validate_product_data(
            {"name": "W", "sku": "A1", "price": 10, "warehouse_id": None}
        )
        assert len(errors) == 0

    # --- initial_quantity validation ---

    def test_valid_quantity(self):
        errors = validate_product_data(
            {"name": "W", "sku": "A1", "price": 10, "initial_quantity": 50}
        )
        assert len(errors) == 0

    def test_zero_quantity_is_valid(self):
        errors = validate_product_data(
            {"name": "W", "sku": "A1", "price": 10, "initial_quantity": 0}
        )
        assert len(errors) == 0

    def test_negative_quantity(self):
        errors = validate_product_data(
            {"name": "W", "sku": "A1", "price": 10, "initial_quantity": -5}
        )
        assert "'initial_quantity' must be a non-negative integer" in errors

    def test_float_quantity(self):
        errors = validate_product_data(
            {"name": "W", "sku": "A1", "price": 10, "initial_quantity": 3.5}
        )
        assert "'initial_quantity' must be a non-negative integer" in errors

    def test_none_quantity_is_ignored(self):
        errors = validate_product_data(
            {"name": "W", "sku": "A1", "price": 10, "initial_quantity": None}
        )
        assert len(errors) == 0

    # --- Multiple errors at once ---

    def test_multiple_errors(self):
        errors = validate_product_data({"warehouse_id": -1, "initial_quantity": -5})
        assert len(errors) >= 4  # name, sku, price missing + warehouse_id + quantity
