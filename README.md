# StockFlow: Inventory Management System

A comprehensive three-part implementation covering code review, database design, and API development for a multi-company, multi-warehouse inventory management platform.

---

## Overview

This project demonstrates production-grade software engineering across three domains:

1. **Part 1: Code Review & Debugging** — Finding and fixing bugs in a broken endpoint
2. **Part 2: Database Design** — Building a normalized schema for complex inventory tracking
3. **Part 3: API Implementation** — Optimizing queries and handling edge cases in a low-stock alerts endpoint

**Total:** 115 tests, all passing. 3 runnable servers with comprehensive Postman test cases.

---

## Part 1: Code Review & Debugging

### Location
`part-1/`

### The Problem

A previous intern wrote a simple product creation endpoint. The code compiles but has critical bugs that would fail in production.

### Original Code

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

### Issues Identified and Solutions

#### A. `request.json` is not validated

**Problem:** If the request body is missing, malformed, or not JSON, `data` will be `None`.

**Impact:** The code crashes with a `TypeError` (trying to subscript `None`) and returns a raw 500 Internal Server Error instead of a proper `400 Bad Request`.

**Solution:** 
```python
data = request.get_json(silent=True)
if data is None:
    return jsonify({"errors": ["Request body must be valid JSON"]}), 400
```

**Reasoning:** `request.get_json(silent=True)` returns `None` on invalid JSON instead of raising an exception. We check explicitly before processing.

---

#### B. Required fields are assumed to exist

**Problem:** The code directly accesses `data['name']`, `data['sku']`, `data['price']`, `data['warehouse_id']`, and `data['initial_quantity']` without checking if they are present.

**Impact:** A missing key raises a `KeyError`, resulting in an unhandled 500 error. Clients get no indication of which field is missing.

**Solution:**
```python
def validate_product_data(data):
    errors = []
    for field in ["name", "sku", "price"]:
        if field not in data or not str(data[field]).strip():
            errors.append(f"'{field}' is required")
    return errors

errors = validate_product_data(data)
if errors:
    return jsonify({"errors": errors}), 400
```

**Reasoning:** Validate all required fields before attempting database operations. Return clear error messages listing all missing fields.

---

#### C. SKU uniqueness is not checked

**Problem:** The requirement states SKUs must be unique across the platform, but the code does not check for duplicates before inserting.

**Impact:** Duplicate SKUs can be created, causing product confusion, incorrect inventory tracking, and broken search/lookup results. If the database has a unique constraint, the error is a raw `IntegrityError` with no friendly message.

**Solution:**
```python
existing = Product.query.filter_by(sku=data["sku"].strip()).first()
if existing:
    return jsonify({"error": "A product with this SKU already exists"}), 409
```

**Reasoning:** Check for existing SKU before attempting insert. Return 409 Conflict with clear message. Also add `UNIQUE (company_id, sku)` constraint at database level as safety net.

---

#### D. Price is stored with the wrong type

**Problem:** The code stores `data['price']` directly without validation or conversion. If the database column uses `Float`, floating-point arithmetic introduces rounding errors.

**Impact:** Financial calculations become inaccurate over time. Prices like `19.99` might be stored as `19.989999999999998`.

**Solution:**
```python
from decimal import Decimal

price = Decimal(str(data["price"]))
product = Product(
    name=data["name"].strip(),
    sku=data["sku"].strip(),
    price=price
)
```

**Reasoning:** Use `Decimal(12,2)` in database and `Decimal` in Python. Avoid float entirely for financial values. `str()` conversion ensures we don't lose precision during the conversion.

---

#### E. Product is incorrectly tied to a single warehouse

**Problem:** The code stores `warehouse_id` as a column on the `Product` model, but the business rule states products can exist in **multiple warehouses**.

**Impact:** This is a fundamental data model design flaw. A product can only belong to one warehouse, making multi-warehouse inventory impossible.

**Solution:**
Remove `warehouse_id` from Product. Link products to warehouses through the `Inventory` table:

```python
class Product(db.Model):
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    sku = Column(String(100), nullable=False, unique=True)
    price = Column(Numeric(12, 2), nullable=False)
    # NO warehouse_id here

class Inventory(db.Model):
    product_id = Column(Integer, ForeignKey("products.id"), primary_key=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), primary_key=True)
    quantity = Column(Integer, nullable=False)
    # One record per product-warehouse pair
```

**Reasoning:** The `Inventory` table serves as the join between products and warehouses, allowing one product to be in multiple warehouses with different quantities per location.

---

#### F. Two separate commits create data inconsistency risk

**Problem:** The product is committed first (`db.session.commit()`), then inventory is inserted and committed separately.

**Impact:** If inventory creation fails after the product commit, the database is left in an inconsistent state: a product exists without any inventory record.

**Solution:**
```python
try:
    product = Product(name=..., sku=..., price=...)
    db.session.add(product)
    db.session.flush()  # Get product.id without committing

    if warehouse_id is not None:
        inventory = Inventory(
            product_id=product.id,
            warehouse_id=warehouse_id,
            quantity=initial_quantity
        )
        db.session.add(inventory)

    db.session.commit()  # Single commit
except Exception:
    db.session.rollback()
    return jsonify({"error": "Failed to create product"}), 500
```

**Reasoning:** Use `flush()` to get the product ID without committing. Add inventory before the final `commit()`. This ensures both operations succeed together or both roll back together.

---

#### G. No transaction rollback on failure

**Problem:** There is no `try/except` block and no `db.session.rollback()`.

**Impact:** Any database error leaves the SQLAlchemy session in a broken state. Subsequent requests on the same session may fail or produce unexpected behavior. Partial writes (from issue F) are never cleaned up.

**Solution:**
```python
try:
    # all operations
    db.session.commit()
except IntegrityError:
    db.session.rollback()
    return jsonify({"error": "Duplicate SKU or invalid reference"}), 409
except Exception:
    db.session.rollback()
    return jsonify({"error": "Internal server error"}), 500
```

**Reasoning:** Wrap database operations in try/except. Always rollback on error. Return appropriate HTTP status codes.

---

#### H. `initial_quantity` is treated as mandatory

**Problem:** The prompt states some fields might be optional, but the code accesses `data['initial_quantity']` unconditionally.

**Impact:** A product creation request fails with a `KeyError` even when inventory setup should be optional.

**Solution:**
```python
if data.get("warehouse_id") is not None:
    inventory = Inventory(
        product_id=product.id,
        warehouse_id=data["warehouse_id"],
        quantity=data.get("initial_quantity", 0)  # default to 0
    )
    db.session.add(inventory)
```

**Reasoning:** Only create an `Inventory` record when a warehouse is specified. Default quantity to 0 if not provided. This allows creating products without inventory setup.

---

#### I. No business-rule validation for inventory

**Problem:** There is no check for negative quantity, invalid warehouse ID, or non-integer quantity values.

**Impact:** Invalid inventory records can be created (e.g., `-50` units), breaking stock calculations, reporting, and downstream order fulfillment logic.

**Solution:**
```python
if "initial_quantity" in data and data["initial_quantity"] is not None:
    if not isinstance(data["initial_quantity"], int) or data["initial_quantity"] < 0:
        errors.append("'initial_quantity' must be a non-negative integer")

if "warehouse_id" in data and data["warehouse_id"] is not None:
    if not isinstance(data["warehouse_id"], int) or data["warehouse_id"] <= 0:
        errors.append("'warehouse_id' must be a positive integer")
```

**Reasoning:** Validate types and ranges before database operations. Return clear error messages.

---

#### J. No proper HTTP status codes

**Problem:** The function returns a success-like JSON dict without an explicit HTTP status code. Flask defaults to `200 OK`, but product creation should return `201 Created`.

**Impact:** Clients cannot reliably distinguish between "product existed already" and "product was just created." API consumers following REST conventions will be confused.

**Solution:**
```python
return jsonify({
    "message": "Product created",
    "product_id": product.id
}), 201  # Explicit 201 Created
```

**Reasoning:** Use proper HTTP status codes: 201 for successful creation, 400 for validation errors, 404 for not found, 409 for conflicts.

---

#### K. No authentication or authorization

**Problem:** The endpoint has no `@login_required` decorator, no role-based access check, and no API key validation.

**Impact:** Any unauthenticated user can create products, enabling catalog flooding, fake product injection, or data corruption by malicious actors.

**Solution:**
```python
from flask_login import login_required

@app.route('/api/products', methods=['POST'])
@login_required  # Require authentication
def create_product():
    # ... rest of code
```

**Reasoning:** Add authentication middleware. In production, verify user has permission to create products for their company.

---

#### L. No idempotency protection

**Problem:** If a client retries a timed-out request (common behind load balancers), the same product and inventory could be created twice.

**Impact:** Duplicate products from retry storms. Without idempotency keys or SKU-based upsert logic, retries silently create duplicates.

**Solution:**
Clients can include an idempotency key in the request header:

```python
idempotency_key = request.headers.get("Idempotency-Key")
if idempotency_key:
    # Check cache or database for previous response
    # Return cached response if exists
```

**Reasoning:** Implement idempotency key tracking. Store the response for each key so retries return the same result without duplicate database entries.

---

#### M. No consistent error response format

**Problem:** The endpoint has no structured error handling. Errors surface as raw Python exceptions converted to generic 500 responses.

**Impact:** Clients cannot programmatically parse error responses. A consistent format like `{"error": "message"}` or `{"errors": ["..."]}` is needed.

**Solution:**
```python
# Validation errors
return jsonify({"errors": ["name is required", "price is required"]}), 400

# Not found
return jsonify({"error": "Warehouse not found"}), 404

# Conflict
return jsonify({"error": "A product with this SKU already exists"}), 409
```

**Reasoning:** Standardize all error responses. Include error message, optionally field names. Always include proper HTTP status code.

---

#### N. `warehouse_id` is not validated against existing warehouses

**Problem:** The code assumes `warehouse_id` refers to a valid warehouse. If the warehouse doesn't exist, the foreign key constraint throws a raw database error.

**Impact:** Clients see a cryptic 500 error instead of a helpful `404 Warehouse not found` message.

**Solution:**
```python
if data.get("warehouse_id") is not None:
    warehouse = db.session.get(Warehouse, data["warehouse_id"])
    if not warehouse:
        return jsonify({"error": "Warehouse not found"}), 404
```

**Reasoning:** Check warehouse existence explicitly before attempting insert. Return 404 with clear message.

---

### Summary of Issues

| # | Issue | Severity | Category |
|---|-------|----------|----------|
| A | `request.json` not validated | Critical | Input validation |
| B | Required fields assumed to exist | Critical | Input validation |
| C | SKU uniqueness not checked | High | Business logic |
| D | Float instead of Decimal for price | Medium | Data types |
| E | `warehouse_id` on Product model | Critical | Schema design |
| F | Two separate commits | Critical | Transaction management |
| G | No transaction rollback | High | Error handling |
| H | `initial_quantity` treated as mandatory | Low | Schema design |
| I | No business-rule validation | Low | Data validation |
| J | No proper HTTP status codes | Medium | API design |
| K | No authentication/authorization | High | Security |
| L | No idempotency protection | Medium | Reliability |
| M | No consistent error response format | Low | API design |
| N | `warehouse_id` not validated | High | Data validation |

### Corrected Implementation

**Key improvements:**
- ✅ Input validation before database operations
- ✅ Single atomic transaction with rollback
- ✅ Proper HTTP status codes (201/400/404/409)
- ✅ Decimal(12,2) for price
- ✅ SKU uniqueness checking
- ✅ Warehouse existence validation
- ✅ Consistent error responses
- ✅ Optional warehouse/inventory creation

### Files

| File | Purpose |
|------|---------|
| `buggy_code.py` | Original problematic code (for reference) |
| `models.py` | SQLAlchemy models (Product, Warehouse, Inventory) |
| `validators.py` | Input validation for product creation |
| `routes.py` | Corrected endpoint implementation |
| `app.py` | Flask app factory |
| `test_validators.py` | 23 unit tests for validators |
| `test_routes.py` | 25 integration tests for endpoint |
| `requirements.txt` | Dependencies |
| `README.md` | Detailed analysis of all 14 issues |

### Test Results

**48 tests passing:**
- 23 validator unit tests (type checking, range validation, required fields)
- 25 route integration tests (201/400/404/409 responses, transaction atomicity)

### Postman Test Cases

All requests are `POST http://localhost:5000/api/products` with header `Content-Type: application/json`.

#### Test 1: Create product with inventory (201)

**Body:**
```json
{
  "name": "Wireless Mouse",
  "sku": "WM-001",
  "price": 29.99,
  "warehouse_id": 1,
  "initial_quantity": 100
}
```

**Expected:** Status 201, `{"message": "Product created", "product_id": 1}`

**Verify:** Product and inventory created, SKU stored correctly, price is Decimal.

---

#### Test 2: Create product without inventory (201)

**Body:**
```json
{
  "name": "USB Cable",
  "sku": "USB-001",
  "price": 9.99
}
```

**Expected:** Status 201. Product created, no inventory record.

---

#### Test 3: Integer price accepted (201)

**Body:**
```json
{
  "name": "Bolt Pack",
  "sku": "BLT-001",
  "price": 5
}
```

**Expected:** Status 201. Price accepted and converted correctly.

---

#### Test 4: Zero initial quantity (201)

**Body:**
```json
{
  "name": "New Widget",
  "sku": "NW-001",
  "price": 14.99,
  "warehouse_id": 1,
  "initial_quantity": 0
}
```

**Expected:** Status 201. Inventory created with quantity=0.

---

#### Test 5: Duplicate SKU (409)

Send again with same SKU as Test 1:

**Body:**
```json
{
  "name": "Different Mouse",
  "sku": "WM-001",
  "price": 19.99
}
```

**Expected:** Status 409, `{"error": "A product with this SKU already exists"}`

---

#### Test 6: Missing required fields (400)

**Body:**
```json
{
  "name": "Keyboard"
}
```

**Expected:** Status 400, `{"errors": ["'sku' is required", "'price' is required"]}`

---

#### Test 7: Empty body (400)

Send with no body or `{}`.

**Expected:** Status 400, `{"errors": ["Request body must be valid JSON"]}` or list all missing required fields.

---

#### Test 8: Invalid JSON (400)

**Body:** `this is not json` (with `Content-Type: application/json`)

**Expected:** Status 400.

---

#### Test 9: Negative price (400)

**Body:**
```json
{
  "name": "Bad Product",
  "sku": "BAD-001",
  "price": -10
}
```

**Expected:** Status 400, `{"errors": ["'price' must be a positive number"]}`

---

#### Test 10: Zero price (400)

**Body:**
```json
{
  "name": "Free Product",
  "sku": "FREE-001",
  "price": 0
}
```

**Expected:** Status 400. Price must be positive.

---

#### Test 11: Non-numeric price (400)

**Body:**
```json
{
  "name": "Bad Price",
  "sku": "BP-001",
  "price": "free"
}
```

**Expected:** Status 400, `{"errors": ["'price' must be a valid decimal number"]}`

---

#### Test 12: Nonexistent warehouse (404)

**Body:**
```json
{
  "name": "Monitor",
  "sku": "MON-001",
  "price": 299.99,
  "warehouse_id": 9999
}
```

**Expected:** Status 404, `{"error": "Warehouse not found"}`

---

#### Test 13: Invalid warehouse_id type (400)

**Body:**
```json
{
  "name": "Monitor",
  "sku": "MON-002",
  "price": 299.99,
  "warehouse_id": "abc"
}
```

**Expected:** Status 400.

---

#### Test 14: Negative quantity (400)

**Body:**
```json
{
  "name": "Bad Qty",
  "sku": "BQ-001",
  "price": 10,
  "warehouse_id": 1,
  "initial_quantity": -5
}
```

**Expected:** Status 400.

---

#### Test 15: Float quantity (400)

**Body:**
```json
{
  "name": "Float Qty",
  "sku": "FQ-001",
  "price": 10,
  "warehouse_id": 1,
  "initial_quantity": 3.5
}
```

**Expected:** Status 400. Quantity must be integer.

---

#### Test 16: Blank name and SKU (400)

**Body:**
```json
{
  "name": "   ",
  "sku": "   ",
  "price": 10
}
```

**Expected:** Status 400. Whitespace-only rejected.

---

#### Test 17: Decimal precision (201)

**Body:**
```json
{
  "name": "Precision Widget",
  "sku": "PW-001",
  "price": 19.99
}
```

**Expected:** Status 201. Price stored as exact `19.99`, not `19.989999...`.

---

#### Test 18: Multiple errors at once (400)

**Body:**
```json
{
  "warehouse_id": -1,
  "initial_quantity": -5
}
```

**Expected:** Status 400. Returns all errors: missing name, sku, price, and invalid warehouse_id and quantity.

---

### Running Part 1

```bash
cd part-1
pip install -r requirements.txt

# Run tests
python -m pytest test_validators.py test_routes.py -v

# Start server
python app.py
# Runs on http://127.0.0.1:5000
```

---

## Part 2: Database Design

### Location
`part-2/`

### The Problem

Design a database schema for a multi-company, multi-warehouse inventory management system with these requirements:

- Companies can have multiple warehouses
- Products can be stored in multiple warehouses with different quantities
- Track when inventory levels change
- Suppliers provide products to companies
- Some products might be "bundles" containing other products

### Schema Design (10 Tables)

#### 1. companies

Stores the tenant/company using the platform.

```sql
CREATE TABLE companies (
    id          BIGSERIAL PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);
```

---

#### 2. users

Users within each company. Needed for audit trail (who made changes).

```sql
CREATE TABLE users (
    id          BIGSERIAL PRIMARY KEY,
    company_id  BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    email       VARCHAR(255) NOT NULL UNIQUE,
    name        VARCHAR(255) NOT NULL,
    role        VARCHAR(50) NOT NULL DEFAULT 'staff',
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    CHECK (role IN ('admin', 'manager', 'staff'))
);
```

---

#### 3. warehouses

Physical storage locations. One company has many warehouses.

```sql
CREATE TABLE warehouses (
    id          BIGSERIAL PRIMARY KEY,
    company_id  BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name        VARCHAR(255) NOT NULL,
    location    VARCHAR(255),
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (company_id, name)
);
```

**Why `UNIQUE (company_id, name)`?** Warehouse names must be unique within a company, but different companies can have warehouses with the same name (e.g., "Main Warehouse").

---

#### 4. products

Product master data. **No `warehouse_id` here** — products link to warehouses through inventory.

```sql
CREATE TABLE products (
    id            BIGSERIAL PRIMARY KEY,
    company_id    BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name          VARCHAR(255) NOT NULL,
    sku           VARCHAR(100) NOT NULL,
    description   TEXT,
    price         DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    product_type  VARCHAR(50) NOT NULL DEFAULT 'normal',
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (company_id, sku),
    CHECK (price >= 0),
    CHECK (product_type IN ('normal', 'bundle'))
);
```

**Why `UNIQUE (company_id, sku)` instead of global?** Multi-tenant design: different companies can independently use the same SKU.

**Why `DECIMAL(12,2)` not `FLOAT`?** Avoids floating-point rounding errors.

---

#### 5. suppliers

Supplier details, scoped to a company.

```sql
CREATE TABLE suppliers (
    id             BIGSERIAL PRIMARY KEY,
    company_id     BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name           VARCHAR(255) NOT NULL,
    contact_email  VARCHAR(255),
    contact_phone  VARCHAR(50),
    address        TEXT,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMP NOT NULL DEFAULT NOW()
);
```

---

#### 6. product_suppliers

Many-to-many: which suppliers provide which products.

```sql
CREATE TABLE product_suppliers (
    product_id     BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    supplier_id    BIGINT NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    supplier_sku   VARCHAR(100),
    lead_time_days INTEGER,
    cost_price     DECIMAL(12,2),
    is_primary     BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (product_id, supplier_id),
    CHECK (lead_time_days IS NULL OR lead_time_days >= 0),
    CHECK (cost_price IS NULL OR cost_price >= 0)
);
```

---

#### 7. inventory

Current stock of each product in each warehouse.

```sql
CREATE TABLE inventory (
    id                BIGSERIAL PRIMARY KEY,
    product_id        BIGINT NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    warehouse_id      BIGINT NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
    quantity          INTEGER NOT NULL DEFAULT 0,
    reserved_quantity INTEGER NOT NULL DEFAULT 0,
    reorder_level     INTEGER,
    created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (product_id, warehouse_id),
    CHECK (quantity >= 0),
    CHECK (reserved_quantity >= 0),
    CHECK (reserved_quantity <= quantity)
);
```

**Why `ON DELETE RESTRICT`?** Prevents accidental deletion of inventory. Force the application to explicitly handle decommissioning.

**Why `reserved_quantity`?** Tracks stock allocated to pending orders. Available stock = `quantity - reserved_quantity`.

---

#### 8. inventory_movements

Immutable audit log of every stock change.

```sql
CREATE TABLE inventory_movements (
    id               BIGSERIAL PRIMARY KEY,
    inventory_id     BIGINT NOT NULL REFERENCES inventory(id) ON DELETE RESTRICT,
    change_type      VARCHAR(50) NOT NULL,
    quantity_change  INTEGER NOT NULL,
    quantity_before  INTEGER NOT NULL,
    quantity_after   INTEGER NOT NULL,
    reference_type   VARCHAR(100),
    reference_id     BIGINT,
    performed_by     BIGINT REFERENCES users(id) ON DELETE SET NULL,
    note             TEXT,
    created_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    CHECK (quantity_change <> 0),
    CHECK (quantity_after >= 0),
    CHECK (change_type IN ('purchase', 'sale', 'return', 'adjustment', 
                           'transfer_in', 'transfer_out', 'damaged', 'bundle_assembly'))
);
```

**Why `quantity_before` and `quantity_after`?** Denormalized for easier auditing (you don't have to replay the full chain).

**Why polymorphic reference (`reference_type`, `reference_id`)?** Allows linking to orders, POs, transfers, etc. without hard-coding FK relationships.

---

#### 9. bundle_components

Self-referencing join: bundle products made up of other products.

```sql
CREATE TABLE bundle_components (
    bundle_product_id     BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    component_product_id  BIGINT NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    component_quantity    INTEGER NOT NULL,
    PRIMARY KEY (bundle_product_id, component_product_id),
    CHECK (component_quantity > 0),
    CHECK (bundle_product_id <> component_product_id)
);
```

**Why self-reference guard?** Prevents a product from being its own component.

---

#### 10. warehouse_transfers

First-class entity for inter-warehouse transfers.

```sql
CREATE TABLE warehouse_transfers (
    id                   BIGSERIAL PRIMARY KEY,
    product_id           BIGINT NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    source_warehouse_id  BIGINT NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
    dest_warehouse_id    BIGINT NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
    quantity             INTEGER NOT NULL,
    status               VARCHAR(50) NOT NULL DEFAULT 'pending',
    initiated_by         BIGINT REFERENCES users(id) ON DELETE SET NULL,
    completed_at         TIMESTAMP,
    created_at           TIMESTAMP NOT NULL DEFAULT NOW(),
    CHECK (quantity > 0),
    CHECK (source_warehouse_id <> dest_warehouse_id),
    CHECK (status IN ('pending', 'in_transit', 'completed', 'cancelled'))
);
```

**Why a separate table?** Links `transfer_out` and `transfer_in` movements atomically with a status lifecycle.

---

### Issues and Design Decisions

#### Issue 1: SKU Uniqueness Scope

**Problem:** Original proposal had `UNIQUE (sku)` globally.

**Why it's wrong:** In a multi-tenant system, different companies should be able to use the same SKU independently.

**Solution:** `UNIQUE (company_id, sku)`

**Reasoning:** Enforces uniqueness within each company's namespace.

---

#### Issue 2: Suppliers Not Scoped to Company

**Problem:** Original proposal had no `company_id` on suppliers.

**Why it's wrong:** Suppliers should be company-specific. Company A's "Parts Inc" is not the same as Company B's "Parts Inc."

**Solution:** Add `company_id BIGINT NOT NULL REFERENCES companies(id)` to suppliers.

**Reasoning:** Each company manages its own supplier list.

---

#### Issue 3: Bundle Nesting Unconstrained

**Problem:** Original `bundle_components` allowed self-references and circular references.

**Why it's wrong:** A product can't be its own component. Circular references (A contains B, B contains A) would cause infinite loops.

**Solution:** `CHECK (bundle_product_id <> component_product_id)`

**Reasoning:** SQL can enforce self-reference check. Circular references require application-level validation (recursive CTE check).

---

#### Issue 4: Enum Values Unchecked

**Problem:** `product_type`, `change_type`, `status`, `role` had no validation.

**Why it's wrong:** Typos like `'nromal'` instead of `'normal'` are silently accepted.

**Solution:** Add `CHECK` constraints:
```sql
CHECK (product_type IN ('normal', 'bundle'))
CHECK (change_type IN ('purchase', 'sale', 'return', ...))
CHECK (status IN ('pending', 'in_transit', 'completed', 'cancelled'))
CHECK (role IN ('admin', 'manager', 'staff'))
```

**Reasoning:** Prevents invalid values at the database level.

---

#### Issue 5: ON DELETE CASCADE on Audit Tables

**Problem:** Original used `ON DELETE CASCADE` on `inventory` and `inventory_movements`.

**Why it's wrong:** If a warehouse is deleted, all inventory records and audit history would be silently destroyed. This violates audit trail requirements.

**Solution:** `ON DELETE RESTRICT`

**Reasoning:** Forces the application to explicitly handle decommissioning. Prevents accidental data loss.

---

#### Issue 6: No User Tracking

**Problem:** Original ignored who made changes.

**Why it's wrong:** An audit trail without knowing who made the change is incomplete.

**Solution:** Add `users` table and `performed_by BIGINT` on `inventory_movements`.

**Reasoning:** Complete audit trail with who/what/when/why.

---

#### Issue 7: No First-Class Warehouse Transfers

**Problem:** Original tracked transfers as two separate movements (`transfer_out`, `transfer_in`).

**Why it's wrong:** The two movements could get out of sync or one could fail while the other succeeds.

**Solution:** Add `warehouse_transfers` table linking both sides atomically with a status.

**Reasoning:** Ensures both sides of a transfer stay in sync and provides a clear lifecycle.

---

#### Issue 8: No Quantity History on Movements

**Problem:** Original `inventory_movements` only had `quantity_change`.

**Why it's wrong:** To understand the full picture, you'd need to replay all changes from the beginning. This is slow and fragile.

**Solution:** Add `quantity_before` and `quantity_after`.

**Reasoning:** Denormalization for auditability. Single record tells the full story without replaying.

---

### Files

| File | Purpose |
|------|---------|
| `schema.sql` | PostgreSQL DDL (10 tables, all constraints, indexes) |
| `models.py` | SQLAlchemy ORM models |
| `test_schema.py` | 35 pytest tests for constraints/relationships |
| `requirements.txt` | Dependencies |
| `README.md` | Full schema documentation |

### Test Results

**35 tests passing:**
- Multi-tenancy (SKU scoping, company isolation)
- Foreign key constraints (RESTRICT/CASCADE)
- Uniqueness constraints
- Check constraints
- Relationships (1:N, M:N, self-referencing)
- Data integrity

### Manual Test Scenarios

See `part-2/README.md` for 11 Python shell scenarios:

1. Create company and verify relationships
2. Warehouse names unique per company
3. Same warehouse name allowed in different company
4. SKU uniqueness per company (not global)
5. Product in multiple warehouses
6. Cannot delete product with inventory (RESTRICT)
7. Bundle cannot reference itself
8. Inventory movement audit trail
9. Cannot delete inventory with movements (RESTRICT)
10. Transfer cannot have same source/dest
11. Product has no warehouse_id column

---

## Part 3: API Implementation

### Location
`part-3/`

### The Problem

Implement a low-stock alerts endpoint that identifies products running low on inventory.

```
GET /api/companies/{company_id}/alerts/low-stock
```

**Business rules:**
- Low stock threshold varies by product type
- Only alert for products with recent sales activity
- Must handle multiple warehouses per company
- Include supplier information for reordering

### Issues Identified and Solutions

#### Issue 1: N+1 Query Problem

**Problem:** Original solution ran 2 extra queries per inventory row in a loop.

```python
for row in rows:
    recent_sales = db.session.query(...)  # Query 1 per row
    supplier = db.session.query(...)       # Query 2 per row
```

**Why it's wrong:** For 1,000 inventory rows, this executes ~2,001 queries total. At scale this is unusably slow.

**Solution:** Use subqueries joined in a single query.

```python
sales_subq = db.session.query(
    InventoryMovement.inventory_id,
    func.abs(func.sum(InventoryMovement.quantity_change)).label("total_sold")
).filter(...).group_by(InventoryMovement.inventory_id).subquery()

# Then INNER JOIN on sales_subq
```

**Reasoning:** Compute sales aggregation once as a subquery, not per-row.

---

#### Issue 2: References Non-Existent Tables

**Problem:** Original used `Sale` and `SaleItem` tables that don't exist.

**Why it's wrong:** The Part 2 schema has no `Sale` table. Sales are tracked through `inventory_movements`.

**Solution:** Query `inventory_movements` where `change_type='sale'`.

```python
sales_subq = db.session.query(
    InventoryMovement.inventory_id,
    func.abs(func.sum(InventoryMovement.quantity_change)).label("total_sold")
).filter(
    InventoryMovement.change_type == "sale",
    InventoryMovement.created_at >= cutoff
).group_by(InventoryMovement.inventory_id).subquery()
```

**Reasoning:** Use the actual schema, not imagined tables.

---

#### Issue 3: Ignores `reserved_quantity`

**Problem:** Original compared raw `inventory.quantity` against threshold.

**Why it's wrong:** Reserved stock is committed to pending orders and shouldn't count as available.

**Solution:** `available_stock = quantity - reserved_quantity`

```python
available_stock = (Inventory.quantity - Inventory.reserved_quantity).label("available_stock")
```

**Reasoning:** Only available stock triggers an alert.

---

#### Issue 4: Ignores `reorder_level`

**Problem:** Original only used hardcoded product-type thresholds.

**Why it's wrong:** Part 2 schema has `reorder_level` per warehouse, allowing customization.

**Solution:** Threshold priority:
1. `inventory.reorder_level` (per product-warehouse)
2. `DEFAULT_THRESHOLDS[product_type]` (product-type default)
3. 20 (global fallback)

```python
threshold = (
    row.reorder_level
    if row.reorder_level is not None
    else DEFAULT_THRESHOLDS.get(row.product_type, 20)
)
```

**Reasoning:** Allows warehouse managers to customize thresholds per location.

---

#### Issue 5: Ignores `is_active` Flags

**Problem:** Original didn't filter inactive products/warehouses.

**Why it's wrong:** Discontinued products shouldn't generate alerts.

**Solution:** Add `WHERE` clause filters.

```python
.filter(
    Product.is_active == True,
    Warehouse.is_active == True
)
```

**Reasoning:** Skip inactive items.

---

#### Issue 6: No Company Validation

**Problem:** Original returned empty 200 for nonexistent `company_id`.

**Why it's wrong:** Clients can't distinguish "no alerts" from "invalid company."

**Solution:** Check company exists, return 404 if not.

```python
company = db.session.get(Company, company_id)
if not company:
    return jsonify({"error": "Company not found"}), 404
```

**Reasoning:** Proper error handling.

---

#### Issue 7: No Sorting

**Problem:** Alerts returned in arbitrary database order.

**Why it's wrong:** Most urgent items (fewest days until stockout) should come first.

**Solution:** Sort by urgency.

```python
alerts.sort(key=lambda a: (a["days_until_stockout"] is None, a["days_until_stockout"] or 0))
```

**Reasoning:** Warehouse managers see critical items at the top.

---

#### Issue 8: No Pagination

**Problem:** Large companies could have thousands of alerts in one response.

**Why it's wrong:** Slow to return, wastes bandwidth.

**Solution:** Add `limit` and `offset` parameters.

```python
paginated = alerts[offset : offset + limit]
return jsonify({
    "alerts": paginated,
    "total_alerts": total_alerts,
    "limit": limit,
    "offset": offset
}), 200
```

**Reasoning:** Return paginated results with total count.

---

### Architecture

The endpoint executes **3 queries total** (no N+1):

1. **Sales subquery** — Aggregates total sold per inventory_id
2. **Main query** — INNER JOIN on sales (excludes zero-sales), LEFT JOIN on supplier
3. **Supplier subquery** — ROW_NUMBER() to pick primary supplier

---

### Stockout Estimation

```
avg_daily_sales = total_sold / lookback_days
days_until_stockout = available_stock / avg_daily_sales
```

---

### Response Format

```json
{
  "alerts": [
    {
      "product_id": 123,
      "product_name": "Widget A",
      "sku": "WID-001",
      "warehouse_id": 456,
      "warehouse_name": "Main Warehouse",
      "current_stock": 15,
      "threshold": 20,
      "days_until_stockout": 4.5,
      "supplier": {
        "id": 789,
        "name": "Parts Corp",
        "contact_email": "orders@parts.com",
        "lead_time_days": 7,
        "cost_price": 5.00
      }
    }
  ],
  "total_alerts": 42,
  "limit": 50,
  "offset": 0
}
```

---

### Query Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `days` | 30 | Lookback window for "recent" sales |
| `limit` | 50 | Max alerts per page |
| `offset` | 0 | Pagination offset |

---

### Edge Cases Handled (16 Total)

| # | Edge Case | Behavior |
|---|-----------|----------|
| 1 | Company doesn't exist | 404 |
| 2 | Company has no inventory | 200, empty alerts |
| 3 | Product has no recent sales | Excluded (INNER JOIN filter) |
| 4 | Sales older than lookback | Not counted |
| 5 | Inactive product | Excluded |
| 6 | Inactive warehouse | Excluded |
| 7 | No supplier linked | Alert appears, supplier=null |
| 8 | No primary supplier | Falls back to any supplier |
| 9 | Stock above threshold | Not included |
| 10 | Reserved stock high | Available = qty - reserved |
| 11 | Custom reorder_level | Overrides product-type default |
| 12 | Other company's data | Strictly filtered by company_id |
| 13 | Invalid query params | 400 error |
| 14 | Zero average sales | days_until_stockout = null |
| 15 | Same product multiple warehouses | Separate alert per warehouse |
| 16 | Large result sets | Paginated via limit/offset |

---

### Files

| File | Purpose |
|------|---------|
| `alerts.py` | Endpoint implementation (single-query architecture) |
| `models.py` | SQLAlchemy models (subset of Part 2) |
| `app.py` | Flask app factory |
| `seed.py` | Database seeding with realistic test data |
| `test_alerts.py` | 32 pytest tests |
| `requirements.txt` | Dependencies |
| `README.md` | Full implementation details |

### Test Results

**32 tests passing:**
- Happy path (7 alerts)
- Threshold logic
- Filtering
- Reserved stock
- Stockout estimation
- Supplier info
- Multi-warehouse
- Sorting
- Pagination
- Custom lookback
- Error handling

### Seed Data

**Company 1 (Acme Corp):** 10 products, 3 warehouses, 2 suppliers

**Expected alerts:** 7 total

| Product | Stock | Threshold | Why |
|---------|-------|-----------|-----|
| Widget A | 5 | 20 | Low stock, recent sales |
| Gadget B | 3 | 20 | Low stock, no supplier |
| Multi-WH G | 8 | 20 | Low in east warehouse |
| Multi-WH G | 4 | 20 | Low in west warehouse |
| Bundle F | 10 | 15 | Bundle type (default=15) |
| Custom Thresh H | 18 | 25 | Custom reorder_level |
| Reserved Stock I | 10 | 20 | Available = 30 - 20 |

**Filtered out (6 products):**
- Bolt C (stock=100, above threshold)
- Stale Item D (no recent sales)
- Discontinued E (is_active=False)
- Widget A in Closed WH (warehouse is_active=False)
- Other Corp product (different company)

---

### Postman Test Cases

All requests are `GET http://127.0.0.1:5001/api/companies/{id}/alerts/low-stock`.

#### Test 1: Happy path (200)

```
GET http://127.0.0.1:5001/api/companies/1/alerts/low-stock
```

**Expected:** Status 200, 7 alerts sorted by urgency.

**Verify:**
- First alert has lowest days_until_stockout
- Last alert has highest days_until_stockout
- Gadget B has supplier=null
- Reserved Stock I shows current_stock=10 (not 30)
- Multi-WH G appears twice

---

#### Test 2: Company not found (404)

```
GET http://127.0.0.1:5001/api/companies/99999/alerts/low-stock
```

**Expected:** Status 404, `{"error": "Company not found"}`

---

#### Test 3: Cross-tenant isolation (200)

```
GET http://127.0.0.1:5001/api/companies/2/alerts/low-stock
```

**Expected:** Status 200, `total_alerts=0` (Other Corp has no alerts in same date range).

---

#### Test 4: Pagination - limit (200)

```
GET http://127.0.0.1:5001/api/companies/1/alerts/low-stock?limit=2
```

**Expected:** Status 200, 7 total alerts but only 2 in array.

---

#### Test 5: Pagination - offset (200)

```
GET http://127.0.0.1:5001/api/companies/1/alerts/low-stock?limit=2&offset=2
```

**Expected:** Status 200, alerts 3-4 returned.

---

#### Test 6: Pagination - offset beyond total (200)

```
GET http://127.0.0.1:5001/api/companies/1/alerts/low-stock?offset=100
```

**Expected:** Status 200, empty alerts array, total_alerts still 7.

---

#### Test 7: Custom lookback window - 20 days (200)

```
GET http://127.0.0.1:5001/api/companies/1/alerts/low-stock?days=20
```

**Expected:** Status 200, fewer alerts (products with sales older than 20 days excluded).

---

#### Test 8: Very short lookback - 1 day (200)

```
GET http://127.0.0.1:5001/api/companies/1/alerts/low-stock?days=1
```

**Expected:** Status 200, 0 alerts (most sales are older than 1 day).

---

#### Test 9: Invalid days parameter (400)

```
GET http://127.0.0.1:5001/api/companies/1/alerts/low-stock?days=abc
```

**Expected:** Status 400, `{"error": "Invalid query parameters"}`

---

#### Test 10: Negative days (400)

```
GET http://127.0.0.1:5001/api/companies/1/alerts/low-stock?days=-5
```

**Expected:** Status 400.

---

#### Test 11: Zero limit (400)

```
GET http://127.0.0.1:5001/api/companies/1/alerts/low-stock?limit=0
```

**Expected:** Status 400.

---

#### Test 12: Negative offset (400)

```
GET http://127.0.0.1:5001/api/companies/1/alerts/low-stock?offset=-1
```

**Expected:** Status 400.

---

#### Test 13: Supplier data structure (200)

From Test 1 response, verify Widget A has:
```json
{
  "supplier": {
    "id": 1,
    "name": "Parts Corp",
    "contact_email": "orders@parts.com",
    "lead_time_days": 7,
    "cost_price": 8.0
  }
}
```

---

#### Test 14: Null supplier (200)

From Test 1 response, verify Gadget B has:
```json
{
  "product_name": "Gadget B",
  "sku": "GDG-002",
  "supplier": null
}
```

---

#### Test 15: Reserved stock deduction (200)

From Test 1 response, verify Reserved Stock I:
```json
{
  "product_name": "Reserved Stock I",
  "sku": "RSV-009",
  "current_stock": 10
}
```

(qty=30, reserved=20, available=10)

---

#### Test 16: Custom threshold (200)

From Test 1 response, verify Custom Thresh H:
```json
{
  "product_name": "Custom Thresh H",
  "sku": "CTH-008",
  "current_stock": 18,
  "threshold": 25
}
```

(Custom reorder_level=25, not default 20)

---

#### Test 17: Sorting by urgency (200)

From Test 1 response, verify alerts sorted ascending by days_until_stockout:
```
alerts[0].days_until_stockout <= alerts[1].days_until_stockout <= ... <= alerts[6].days_until_stockout
```

---

### Running Part 3

```bash
cd part-3
pip install -r requirements.txt

# Seed database
python seed.py

# Run tests
python -m pytest test_alerts.py -v

# Start server
python app.py
# Runs on http://127.0.0.1:5001
```

---

## Quick Reference

### Startup Commands

```bash
# Part 1
cd part-1 && python app.py
# http://127.0.0.1:5000

# Part 2 (tests only)
cd part-2 && python -m pytest test_schema.py -v

# Part 3
cd part-3 && python seed.py && python app.py
# http://127.0.0.1:5001
```

### Test Commands

```bash
# Part 1: 48 tests
cd part-1 && python -m pytest test_validators.py test_routes.py -v

# Part 2: 35 tests
cd part-2 && python -m pytest test_schema.py -v

# Part 3: 32 tests
cd part-3 && python -m pytest test_alerts.py -v
```

**Total: 115 tests, all passing**

---

## Summary

### Part 1: Code Review & Debugging
- 14 critical, high, medium, and low severity issues identified
- 14 detailed explanations of why each issue matters
- 14 code solutions with reasoning
- 48 tests (23 validators + 25 routes)
- 18 Postman test cases

### Part 2: Database Design
- 10-table normalized schema
- 8 critical design decisions explained
- Multi-tenancy support
- Audit trail with `inventory_movements`
- 35 tests
- 11 manual verification scenarios

### Part 3: API Implementation
- Single-query architecture (no N+1)
- 8 critical issues fixed
- 16 edge cases handled
- 32 tests
- 17 Postman test cases
- Realistic seed data with 7 expected alerts

**Total:** 115 tests, all passing
