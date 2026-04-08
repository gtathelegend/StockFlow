# Part 1: Code Review & Debugging

## The Problem

A previous intern wrote an API endpoint for adding new products. The code compiles but doesn't work as expected in production.

### Original Buggy Code

```python
@app.route('/api/products', methods=['POST'])
def create_product():
    data = request.json

    product = Product(
        name=data['name'],
        sku=data['sku'],
        price=data['price'],
        warehouse_id=data['warehouse_id']
    )

    db.session.add(product)
    db.session.commit()

    inventory = Inventory(
        product_id=product.id,
        warehouse_id=data['warehouse_id'],
        quantity=data['initial_quantity']
    )

    db.session.add(inventory)
    db.session.commit()

    return {"message": "Product created", "product_id": product.id}
```

### Business Rules

- Products can exist in multiple warehouses
- SKUs must be unique across the platform
- Price can be decimal values
- Some fields might be optional

---

## Issues Identified

### A. `request.json` is not validated

If the request body is missing, malformed, or not JSON, `data` will be `None`.

**Impact:** The code crashes with a `TypeError` (trying to subscript `None`) and returns a raw 500 Internal Server Error instead of a proper `400 Bad Request`.

---

### B. Required fields are assumed to exist

The code directly accesses `data['name']`, `data['sku']`, `data['price']`, `data['warehouse_id']`, and `data['initial_quantity']` without checking if they are present.

**Impact:** A missing key raises a `KeyError`, resulting in an unhandled 500 error. Clients get no indication of which field is missing.

---

### C. SKU uniqueness is not checked

The requirement states SKUs must be unique across the platform, but the code does not check for duplicates before inserting.

**Impact:** Duplicate SKUs can be created, causing product confusion, incorrect inventory tracking, and broken search/lookup results. If the database has a unique constraint, the error is a raw `IntegrityError` with no friendly message.

---

### D. Price is stored with the wrong type

The code stores `data['price']` directly without validation or conversion. If the database column uses `Float`, floating-point arithmetic introduces rounding errors (e.g., `0.1 + 0.2 != 0.3`).

**Impact:** Financial calculations become inaccurate over time. Prices like `19.99` might be stored as `19.989999999999998`. The fix is to use `Decimal` in Python and `NUMERIC(10, 2)` in the database.

---

### E. Product is incorrectly tied to a single warehouse (Data Model Flaw)

The code stores `warehouse_id` as a column on the `Product` model, but the business rule states products can exist in **multiple warehouses**.

**Impact:** This is a fundamental data model design flaw. A product can only belong to one warehouse, making multi-warehouse inventory impossible. The `Inventory` table should be the sole link between products and warehouses -- `warehouse_id` should not exist on `Product` at all.

---

### F. Two separate commits create data inconsistency risk

The product is committed first (`db.session.commit()`), then inventory is inserted and committed separately.

**Impact:** If inventory creation fails after the product commit, the database is left in an inconsistent state: a product exists without any inventory record. Both operations should be part of a single atomic transaction using `db.session.flush()` (to get the product ID) followed by a single `db.session.commit()`.

---

### G. No transaction rollback on failure

There is no `try/except` block and no `db.session.rollback()`.

**Impact:** Any database error leaves the SQLAlchemy session in a broken state. Subsequent requests on the same session may fail or produce unexpected behavior. Partial writes (from issue F) are never cleaned up.

---

### H. `initial_quantity` is treated as mandatory

The prompt states some fields might be optional, but the code accesses `data['initial_quantity']` unconditionally.

**Impact:** A product creation request fails with a `KeyError` even when inventory setup should be optional. The fix is to use `data.get('initial_quantity', 0)` and only create an `Inventory` record when a warehouse is specified.

---

### I. No business-rule validation for inventory

There is no check for negative quantity, zero or negative warehouse IDs, or non-integer quantity values.

**Impact:** Invalid inventory records can be created (e.g., `-50` units), breaking stock calculations, reporting, and downstream order fulfillment logic.

---

### J. No proper HTTP status codes

The function returns a success-like JSON dict without an explicit HTTP status code. Flask defaults to `200 OK`, but product creation should return `201 Created`.

**Impact:** Clients cannot reliably distinguish between "product existed already" and "product was just created." API consumers following REST conventions will be confused.

---

### K. No authentication or authorization

The endpoint has no `@login_required` decorator, no role-based access check, and no API key validation.

**Impact:** Any unauthenticated user can create products, enabling catalog flooding, fake product injection, or data corruption by malicious actors.

---

### L. No idempotency protection

If a client retries a timed-out request (common behind load balancers), the same product and inventory could be created twice.

**Impact:** Duplicate products from retry storms. Without idempotency keys or SKU-based upsert logic, retries silently create duplicates (or fail with a confusing IntegrityError if SKU uniqueness is enforced at the DB level).

---

### M. No consistent error response format

The endpoint has no structured error handling. Errors surface as raw Python exceptions converted to generic 500 responses.

**Impact:** Clients cannot programmatically parse error responses. A consistent format like `{"error": "message", "field": "name"}` or `{"errors": ["..."]}` is needed for frontend form validation and API consumer error handling.

---

### N. `warehouse_id` is not validated against existing warehouses

The code assumes `warehouse_id` refers to a valid warehouse. If the warehouse doesn't exist, the foreign key constraint throws a raw database error.

**Impact:** Clients see a cryptic 500 error instead of a helpful `404 Warehouse not found` message. The fix is to query for the warehouse before creating the inventory record.

---

## Issues by Severity

| Severity | Issue | Key |
|----------|-------|-----|
| **Critical** | Two separate commits (data inconsistency) | F |
| **Critical** | No input validation (crashes on bad input) | A, B |
| **Critical** | `warehouse_id` on Product (wrong data model) | E |
| **High** | No SKU uniqueness check | C |
| **High** | No rollback on failure | G |
| **High** | No warehouse existence validation | N |
| **Medium** | Float instead of Decimal for price | D |
| **Medium** | No authentication/authorization | K |
| **Medium** | No proper HTTP status codes | J |
| **Medium** | No idempotency protection | L |
| **Low** | Optional fields not handled gracefully | H |
| **Low** | No business-rule validation on quantity | I |
| **Low** | No consistent error response format | M |

---

## Corrected Implementation

### Data Model (`models.py`)

Key changes from the buggy version:

- **Removed `warehouse_id` from `Product`** -- products are linked to warehouses only through the `Inventory` table
- **Added `unique=True` on `sku`** -- enforces uniqueness at the database level as a safety net
- **Used `Numeric(10, 2)` for `price`** -- avoids floating-point precision errors
- **Added `UniqueConstraint` on `(product_id, warehouse_id)` in `Inventory`** -- prevents duplicate inventory records for the same product-warehouse pair

### Validation (`validators.py`)

- Checks that the request body is valid JSON
- Validates required fields (`name`, `sku`, `price`) are present and non-empty
- Validates `price` is a positive decimal number
- Validates `warehouse_id` (if provided) is a positive integer
- Validates `initial_quantity` (if provided) is a non-negative integer

### Route (`routes.py`)

Key fixes applied:

1. **`request.get_json(silent=True)`** instead of `request.json` -- returns `None` instead of raising on bad JSON
2. **Input validation** before any database operations
3. **SKU uniqueness check** with a `409 Conflict` response
4. **Warehouse existence check** with a `404 Not Found` response
5. **Single atomic transaction** using `flush()` + one `commit()`
6. **`try/except` with `rollback()`** on any database error
7. **Explicit HTTP status codes** (`201`, `400`, `404`, `409`, `500`)
8. **`jsonify()` for all responses** with consistent error format
9. **Optional `warehouse_id` and `initial_quantity`** -- inventory is only created when a warehouse is specified

### Running the Application

```bash
cd part-1
pip install -r requirements.txt
python app.py
```

### Example Requests

**Create a product with inventory:**

```bash
curl -X POST http://localhost:5000/api/products \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Wireless Mouse",
    "sku": "WM-001",
    "price": 29.99,
    "warehouse_id": 1,
    "initial_quantity": 100
  }'
```

**Create a product without inventory:**

```bash
curl -X POST http://localhost:5000/api/products \
  -H "Content-Type: application/json" \
  -d '{
    "name": "USB Cable",
    "sku": "USB-001",
    "price": 9.99
  }'
```

**Expected error responses:**

```json
// 400 - Missing fields
{"errors": ["'name' is required", "'price' is required"]}

// 409 - Duplicate SKU
{"error": "A product with this SKU already exists"}

// 404 - Invalid warehouse
{"error": "Warehouse not found"}
```
