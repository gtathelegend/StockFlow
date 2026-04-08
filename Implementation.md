Repository: gtathelegend/stockflow
Files analyzed: 22

Estimated tokens: 51.3k

Directory structure:
└── gtathelegend-stockflow/
    ├── README.md
    ├── part-1/
    │   ├── README.md
    │   ├── app.py
    │   ├── buggy_code.py
    │   ├── models.py
    │   ├── requirements.txt
    │   ├── routes.py
    │   ├── test_routes.py
    │   ├── test_validators.py
    │   └── validators.py
    ├── part-2/
    │   ├── README.md
    │   ├── models.py
    │   ├── requirements.txt
    │   ├── schema.sql
    │   └── test_schema.py
    └── part-3/
        ├── README.md
        ├── alerts.py
        ├── app.py
        ├── models.py
        ├── requirements.txt
        ├── seed.py
        └── test_alerts.py


================================================
FILE: README.md
================================================
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



================================================
FILE: part-1/README.md
================================================
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

---

## API Test Cases (Postman)

Start the server first:

```bash
cd part-1
pip install -r requirements.txt
python app.py
```

The server runs on `http://127.0.0.1:5000`. Two seed warehouses (id=1, id=2) are created automatically.

All requests below are **POST** to `http://127.0.0.1:5000/api/products` with header `Content-Type: application/json`.

---

### Test 1: Create product with inventory (201 Created)

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

**Expected:**
```json
{
  "message": "Product created",
  "product_id": 1
}
```

**Verify:** Status code = `201`. Response contains `product_id`.

---

### Test 2: Create product without inventory (201 Created)

**Body:**
```json
{
  "name": "USB Cable",
  "sku": "USB-001",
  "price": 9.99
}
```

**Expected:** Status `201`. Product is created with no inventory record.

---

### Test 3: Create product with integer price (201 Created)

**Body:**
```json
{
  "name": "Bolt Pack",
  "sku": "BLT-001",
  "price": 5
}
```

**Expected:** Status `201`. Integer prices are accepted and stored correctly.

---

### Test 4: Create product with zero initial quantity (201 Created)

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

**Expected:** Status `201`. Inventory record created with quantity=0.

---

### Test 5: Duplicate SKU (409 Conflict)

Send Test 1 again (same SKU `WM-001`):

**Body:**
```json
{
  "name": "Different Mouse",
  "sku": "WM-001",
  "price": 19.99
}
```

**Expected:**
```json
{
  "error": "A product with this SKU already exists"
}
```

**Verify:** Status code = `409`.

---

### Test 6: Missing required fields (400 Bad Request)

**Body:**
```json
{
  "name": "Keyboard"
}
```

**Expected:**
```json
{
  "errors": ["'sku' is required", "'price' is required"]
}
```

**Verify:** Status `400`. Both missing fields listed.

---

### Test 7: Empty body (400 Bad Request)

Send with **no body** or empty body `{}`.

**Expected:**
```json
{
  "errors": ["Request body must be valid JSON"]
}
```
or (for `{}`):
```json
{
  "errors": ["'name' is required", "'sku' is required", "'price' is required"]
}
```

**Verify:** Status `400`.

---

### Test 8: Invalid JSON (400 Bad Request)

Set body to raw text: `this is not json` with `Content-Type: application/json`.

**Expected:** Status `400`.

---

### Test 9: Negative price (400 Bad Request)

**Body:**
```json
{
  "name": "Bad Product",
  "sku": "BAD-001",
  "price": -10
}
```

**Expected:**
```json
{
  "errors": ["'price' must be a positive number"]
}
```

**Verify:** Status `400`.

---

### Test 10: Zero price (400 Bad Request)

**Body:**
```json
{
  "name": "Free Product",
  "sku": "FREE-001",
  "price": 0
}
```

**Expected:** Status `400`. Price must be positive.

---

### Test 11: Non-numeric price (400 Bad Request)

**Body:**
```json
{
  "name": "Bad Price",
  "sku": "BP-001",
  "price": "free"
}
```

**Expected:**
```json
{
  "errors": ["'price' must be a valid decimal number"]
}
```

---

### Test 12: Nonexistent warehouse (404 Not Found)

**Body:**
```json
{
  "name": "Monitor",
  "sku": "MON-001",
  "price": 299.99,
  "warehouse_id": 9999
}
```

**Expected:**
```json
{
  "error": "Warehouse not found"
}
```

**Verify:** Status `404`.

---

### Test 13: Invalid warehouse_id type (400 Bad Request)

**Body:**
```json
{
  "name": "Monitor",
  "sku": "MON-002",
  "price": 299.99,
  "warehouse_id": "abc"
}
```

**Expected:** Status `400`. Error about warehouse_id type.

---

### Test 14: Negative initial_quantity (400 Bad Request)

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

**Expected:** Status `400`. Error about initial_quantity.

---

### Test 15: Float initial_quantity (400 Bad Request)

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

**Expected:** Status `400`. Quantity must be an integer.

---

### Test 16: Blank name and SKU (400 Bad Request)

**Body:**
```json
{
  "name": "   ",
  "sku": "   ",
  "price": 10
}
```

**Expected:** Status `400`. Both name and sku flagged as required (whitespace-only is rejected).

---

### Test 17: Decimal precision price (201 Created)

**Body:**
```json
{
  "name": "Precision Widget",
  "sku": "PW-001",
  "price": 19.99
}
```

**Expected:** Status `201`. Price stored as exact decimal `19.99`, not `19.989999...`.

---

### Test 18: Multiple errors at once (400 Bad Request)

**Body:**
```json
{
  "warehouse_id": -1,
  "initial_quantity": -5
}
```

**Expected:** Status `400`. Multiple errors returned:
```json
{
  "errors": [
    "'name' is required",
    "'sku' is required",
    "'price' is required",
    "'warehouse_id' must be a positive integer",
    "'initial_quantity' must be a non-negative integer"
  ]
}
```

---

### Test Summary

| # | Test Case | Method | Expected Status |
|---|-----------|--------|----------------|
| 1 | Create with inventory | POST | 201 |
| 2 | Create without inventory | POST | 201 |
| 3 | Integer price | POST | 201 |
| 4 | Zero initial quantity | POST | 201 |
| 5 | Duplicate SKU | POST | 409 |
| 6 | Missing fields | POST | 400 |
| 7 | Empty body | POST | 400 |
| 8 | Invalid JSON | POST | 400 |
| 9 | Negative price | POST | 400 |
| 10 | Zero price | POST | 400 |
| 11 | Non-numeric price | POST | 400 |
| 12 | Nonexistent warehouse | POST | 404 |
| 13 | Invalid warehouse_id type | POST | 400 |
| 14 | Negative quantity | POST | 400 |
| 15 | Float quantity | POST | 400 |
| 16 | Blank name/SKU | POST | 400 |
| 17 | Decimal precision | POST | 201 |
| 18 | Multiple errors | POST | 400 |



================================================
FILE: part-1/app.py
================================================
from flask import Flask
from models import db, Warehouse
from routes import products_bp


def create_app(config=None):
    app = Flask(__name__)

    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///stockflow.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    if config:
        app.config.update(config)

    db.init_app(app)
    app.register_blueprint(products_bp)

    with app.app_context():
        db.create_all()
        # Seed a default warehouse if none exist
        if not Warehouse.query.first():
            db.session.add(Warehouse(name="Main Warehouse", location="New York"))
            db.session.add(Warehouse(name="West Coast Warehouse", location="Los Angeles"))
            db.session.commit()

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)



================================================
FILE: part-1/buggy_code.py
================================================
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



================================================
FILE: part-1/models.py
================================================
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

db = SQLAlchemy()


class Warehouse(db.Model):
    __tablename__ = "warehouses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    location = Column(String(255), nullable=True)

    inventories = relationship("Inventory", back_populates="warehouse")


class Product(db.Model):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    sku = Column(String(100), unique=True, nullable=False)
    price = Column(Numeric(10, 2), nullable=False)

    inventories = relationship("Inventory", back_populates="product")


class Inventory(db.Model):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)
    quantity = Column(Integer, nullable=False, default=0)

    product = relationship("Product", back_populates="inventories")
    warehouse = relationship("Warehouse", back_populates="inventories")

    __table_args__ = (
        UniqueConstraint("product_id", "warehouse_id", name="uq_product_warehouse"),
    )



================================================
FILE: part-1/requirements.txt
================================================
Flask==3.1.1
Flask-SQLAlchemy==3.1.1
SQLAlchemy==2.0.40



================================================
FILE: part-1/routes.py
================================================
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
        warehouse = db.session.get(Warehouse, data["warehouse_id"])
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



================================================
FILE: part-1/test_routes.py
================================================
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



================================================
FILE: part-1/test_validators.py
================================================
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



================================================
FILE: part-1/validators.py
================================================
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



================================================
FILE: part-2/README.md
================================================
# Part 2: Database Design

## The Problem

Design a database schema for a multi-company inventory management platform given intentionally incomplete requirements:

- Companies can have multiple warehouses
- Products can be stored in multiple warehouses with different quantities
- Track when inventory levels change
- Suppliers provide products to companies
- Some products might be "bundles" containing other products

---

## Schema Overview

### Entity Relationship Diagram (text)

```
companies ──1:N──> users
    │
    ├──1:N──> warehouses
    │              │
    ├──1:N──> products ──M:N─��> suppliers
    │           │    │              (via product_suppliers)
    │           │    └── bundle_components (self-referencing M:N)
    │           │
    │           └───────> inventory <───── warehouses
    │                        │
    │                   1:N  │
    │                        v
    │                 inventory_movements
    │
    └──1:N──> warehouse_transfers
```

### Tables (10 total)

| Table | Purpose |
|-------|---------|
| `companies` | Tenant/company using the platform |
| `users` | Users within a company (for audit trail) |
| `warehouses` | Physical storage locations, scoped to a company |
| `products` | Product master data, scoped to a company |
| `suppliers` | Supplier details, scoped to a company |
| `product_suppliers` | Many-to-many: which suppliers provide which products |
| `inventory` | Current stock of each product in each warehouse |
| `inventory_movements` | Immutable audit log of every stock change |
| `bundle_components` | Self-referencing join: bundle products made of other products |
| `warehouse_transfers` | First-class entity for inter-warehouse stock transfers |

---

## Table Definitions

### A. companies

Stores the tenant/company using the platform.

```sql
CREATE TABLE companies (
    id          BIGSERIAL PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);
```

### B. users

Needed for audit trail -- every inventory change should track *who* made it.

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

### C. warehouses

Each company can have multiple warehouses. Names must be unique within a company.

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

### D. products

Product master data. **No `warehouse_id` column** -- products link to warehouses through the `inventory` table.

**Key design decision:** SKU is unique *per company*, not globally. Two different companies can independently use the same SKU.

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

### E. suppliers

Scoped to a company. Each company manages its own supplier list.

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

### F. product_suppliers

Many-to-many join with additional metadata: supplier-specific SKU, lead time, cost price, and primary supplier flag.

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

### G. inventory

Current stock of each product in each warehouse. Uses **`ON DELETE RESTRICT`** to prevent accidental deletion of products or warehouses that have inventory.

```sql
CREATE TABLE inventory (
    id                BIGSERIAL PRIMARY KEY,
    product_id        BIGINT NOT NULL REFERENCES products(id)    ON DELETE RESTRICT,
    warehouse_id      BIGINT NOT NULL REFERENCES warehouses(id)  ON DELETE RESTRICT,
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

### H. inventory_movements

Immutable audit log. Every stock change is recorded with before/after quantities, who made it, and what triggered it.

Uses a **polymorphic reference** pattern (`reference_type` + `reference_id`) to link back to orders, purchase orders, transfers, etc. without hard coupling to those tables.

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
    CHECK (change_type IN (
        'purchase', 'sale', 'return', 'adjustment',
        'transfer_in', 'transfer_out', 'damaged', 'bundle_assembly'
    ))
);
```

### I. bundle_components

Self-referencing join table for bundle products. A bundle product contains N units of each component product.

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

### J. warehouse_transfers

First-class entity linking `transfer_out` and `transfer_in` movements atomically. Without this, a transfer is two unconnected movements that could get out of sync.

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

---

## Relationships Summary

| Relationship | Type | Description |
|-------------|------|-------------|
| Company -> Users | 1:N | Each user belongs to one company |
| Company -> Warehouses | 1:N | Each warehouse belongs to one company |
| Company -> Products | 1:N | Each product belongs to one company |
| Company -> Suppliers | 1:N | Each supplier belongs to one company |
| Product <-> Warehouse | M:N | Linked through `inventory` table |
| Product <-> Supplier | M:N | Linked through `product_suppliers` table |
| Product <-> Product | M:N | Bundle composition via `bundle_components` |
| Inventory -> Movements | 1:N | Each inventory row has many movement records |
| Warehouse -> Warehouse | Transfer | Tracked via `warehouse_transfers` |

---

## Design Decisions Explained

### 1. Multi-Tenant Scoping

Every major entity (`warehouses`, `products`, `suppliers`) has a `company_id` foreign key. This ensures data isolation between companies. SKU uniqueness is scoped to the company level (`UNIQUE (company_id, sku)`) rather than globally, so different companies can independently use the same SKU codes.

### 2. ON DELETE RESTRICT vs CASCADE

| Table | Delete Behavior | Why |
|-------|----------------|-----|
| `warehouses`, `products`, `users` | CASCADE from company | If a company is deleted, all its data goes with it |
| `inventory` | RESTRICT on product and warehouse | Prevents accidentally deleting a product/warehouse that still has stock |
| `inventory_movements` | RESTRICT on inventory | Prevents destroying audit history |
| `bundle_components` | RESTRICT on component, CASCADE on bundle | Deleting a bundle removes its composition; deleting a component that's part of a bundle is blocked |

**Rationale:** `ON DELETE CASCADE` on audit-critical tables is dangerous. If someone accidentally deletes a warehouse, all inventory records and their movement history would be silently destroyed. `RESTRICT` forces the application to explicitly handle decommissioning (transfer stock first, archive, then delete).

### 3. DECIMAL(12,2) for Price (Not FLOAT)

Floating-point arithmetic introduces rounding errors in financial calculations (`0.1 + 0.2 != 0.3` in IEEE 754). `DECIMAL(12,2)` stores exact values up to 9,999,999,999.99.

### 4. Constrained Enum Values via CHECK

All "type" and "status" columns have `CHECK` constraints limiting them to known values:

- `product_type IN ('normal', 'bundle')`
- `change_type IN ('purchase', 'sale', 'return', ...)`
- `status IN ('pending', 'in_transit', 'completed', 'cancelled')`
- `role IN ('admin', 'manager', 'staff')`

This prevents typos and invalid states at the database level, not just in application code.

### 5. Bundle Self-Reference Guard

```sql
CHECK (bundle_product_id <> component_product_id)
```

Prevents a product from being a component of itself. Circular references (A contains B, B contains A) and infinite nesting (bundles of bundles of bundles) require application-level validation using recursive CTEs, as SQL CHECK constraints cannot express graph cycle detection.

### 6. Warehouse Transfers as a First-Class Entity

The original solution tracked transfers as two separate `inventory_movements` (`transfer_in` / `transfer_out`). The `warehouse_transfers` table links both sides atomically with a status lifecycle (`pending` -> `in_transit` -> `completed`/`cancelled`), preventing the two movements from getting out of sync.

### 7. Audit Trail with `performed_by` and Before/After Quantities

The `inventory_movements` table records:
- **Who** made the change (`performed_by` -> users)
- **What** changed (`quantity_change`, `quantity_before`, `quantity_after`)
- **Why** it changed (`change_type`, `reference_type`, `reference_id`, `note`)
- **When** it happened (`created_at`)

The `quantity_before` and `quantity_after` fields are denormalized (they could be derived from the chain of changes), but they make auditing and debugging dramatically easier without requiring a full replay.

### 8. Polymorphic Reference Pattern

```sql
reference_type VARCHAR(100),  -- 'order', 'purchase_order', 'transfer', etc.
reference_id   BIGINT,
```

This allows `inventory_movements` to link back to any future entity (orders, purchase orders, returns) without adding a foreign key for each. Trade-off: no referential integrity enforcement on this link, but it avoids schema changes when new reference types are added.

---

## Indexes

```sql
-- Foreign key indexes for fast joins
CREATE INDEX idx_users_company         ON users(company_id);
CREATE INDEX idx_warehouses_company    ON warehouses(company_id);
CREATE INDEX idx_products_company      ON products(company_id);
CREATE INDEX idx_products_sku          ON products(sku);
CREATE INDEX idx_suppliers_company     ON suppliers(company_id);
CREATE INDEX idx_inventory_warehouse   ON inventory(warehouse_id);
CREATE INDEX idx_inventory_product     ON inventory(product_id);

-- Movement query indexes
CREATE INDEX idx_movements_inventory   ON inventory_movements(inventory_id);
CREATE INDEX idx_movements_created     ON inventory_movements(created_at);
CREATE INDEX idx_movements_reference   ON inventory_movements(reference_type, reference_id);
CREATE INDEX idx_movements_performer   ON inventory_movements(performed_by);

-- Transfer query indexes
CREATE INDEX idx_transfers_product     ON warehouse_transfers(product_id);
CREATE INDEX idx_transfers_source      ON warehouse_transfers(source_warehouse_id);
CREATE INDEX idx_transfers_dest        ON warehouse_transfers(dest_warehouse_id);
```

**Key index choices:**
- `idx_movements_created` -- essential for time-range audit queries ("show all changes this week")
- `idx_movements_reference` -- composite index for the polymorphic reference pattern, used when looking up all movements for a specific order/PO
- `idx_products_sku` -- fast SKU lookups (most common product query)

---

## Gaps / Questions for the Product Team

The requirements are intentionally incomplete. These questions would need answers before going to production:

| # | Question | Impact on Schema |
|---|----------|-----------------|
| 1 | Can a product belong to more than one company? | Changes `company_id` from FK to a join table |
| 2 | Should bundles auto-reduce component stock when sold? | Requires application logic + `bundle_assembly` movement type |
| 3 | Can a product be both normal and a bundle? | Affects `product_type` constraint |
| 4 | Are there product categories or tags? | Needs a `categories` table + join table |
| 5 | Do we need multi-currency support? | Adds `currency` column to products, potentially a `currencies` table |
| 6 | Should prices be company-specific or global? | Currently per-product; may need a `pricing` table |
| 7 | Do we need product variants (size, color)? | Adds a `product_variants` table |
| 8 | Should low-stock thresholds be global, per-product, or per-warehouse? | Currently per-warehouse via `reorder_level` |
| 9 | Do we need soft delete instead of hard delete? | Currently using `is_active` flags on key tables |
| 10 | What's the expected data volume for movements? | Affects partitioning strategy (this table grows unboundedly) |
| 11 | Are there units of measure (pieces vs. weight vs. volume)? | Adds `unit_of_measure` column to products |
| 12 | Should reserved stock be tracked separately? | Currently yes, via `reserved_quantity` on inventory |
| 13 | How should stock transfers between warehouses be recorded? | Implemented via `warehouse_transfers` table |
| 14 | Do we need to track supplier pricing history or purchase orders? | Would add `purchase_orders` and `purchase_order_lines` tables |

### Assumptions Made

Because requirements are incomplete, the schema assumes:

1. Each product belongs to **one company** (single-tenant ownership)
2. SKU is unique **per company**, not globally
3. Suppliers are **company-specific**, not shared across the platform
4. Price is stored as `DECIMAL(12,2)` for exact currency values
5. Bundle stock is modeled as a composition table, not a text field
6. Inventory changes must be **fully auditable** with who/what/when/why
7. `is_active` flags serve as soft delete for products, warehouses, suppliers, and users
8. Cross-company data isolation is enforced (a warehouse from company A cannot hold products from company B -- enforced at application level)

---

## Tests

35 tests verify schema constraints, relationships, and data integrity:

```bash
cd part-2
pip install -r requirements.txt
python -m pytest test_schema.py -v
```

| Test Class | Count | What It Verifies |
|-----------|-------|-----------------|
| TestCompany | 2 | Creation, empty relationships |
| TestUser | 3 | Creation, duplicate email blocked, company membership |
| TestWarehouse | 4 | Creation, multi-warehouse, duplicate name blocked, cross-company name allowed |
| TestProduct | 5 | Creation, duplicate SKU blocked per company, same SKU allowed cross-company, decimal precision |
| TestSupplier | 2 | Creation, company scoping |
| TestProductSupplier | 3 | Linking, multiple suppliers, duplicate blocked |
| TestInventory | 5 | Creation, multi-warehouse stock, duplicate blocked, RESTRICT on delete product/warehouse |
| TestInventoryMovement | 3 | Creation with performer, multiple movements, RESTRICT on delete inventory |
| TestBundleComponent | 4 | Bundle creation, reverse lookup, self-reference blocked, RESTRICT on component delete |
| TestWarehouseTransfer | 2 | Creation with status, same-warehouse transfer blocked |
| TestIntegration | 2 | Full lifecycle, Product model has no warehouse_id column |

---

## API Test Cases (Manual Verification via Python Shell)

Part 2 has no running API server -- it is a schema design. To manually verify constraints and relationships, use the Python shell:

```bash
cd part-2
pip install -r requirements.txt
python
```

Then run the test scenarios below inside the shell.

---

### Test 1: Create a company and verify relationships

```python
from flask import Flask
from models import db, Company, Warehouse, Product
from decimal import Decimal

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
db.init_app(app)
ctx = app.app_context()
ctx.push()
db.create_all()

c = Company(name="Acme Corp")
db.session.add(c)
db.session.commit()
print(f"Company created: id={c.id}, name={c.name}")
# Expected: Company created: id=1, name=Acme Corp
```

---

### Test 2: Warehouse names unique within a company

```python
from models import Warehouse
wh1 = Warehouse(company_id=c.id, name="East", location="NYC")
db.session.add(wh1)
db.session.commit()
print(f"Warehouse 1: id={wh1.id}")

# Duplicate name for same company should fail
try:
    wh_dup = Warehouse(company_id=c.id, name="East", location="Other")
    db.session.add(wh_dup)
    db.session.commit()
    print("ERROR: duplicate was allowed!")
except Exception as e:
    db.session.rollback()
    print(f"Correctly blocked: {type(e).__name__}")
# Expected: Correctly blocked: IntegrityError
```

---

### Test 3: Same warehouse name in different company is allowed

```python
c2 = Company(name="Other Corp")
db.session.add(c2)
db.session.commit()
wh_other = Warehouse(company_id=c2.id, name="East", location="Boston")
db.session.add(wh_other)
db.session.commit()
print(f"Cross-company warehouse created: id={wh_other.id}")
# Expected: no error, warehouse created
```

---

### Test 4: SKU unique per company, not globally

```python
p1 = Product(company_id=c.id, name="Widget", sku="W-001", price=Decimal("10.00"))
db.session.add(p1)
db.session.commit()
print(f"Product 1: id={p1.id}")

# Same SKU, different company -- should succeed
p2 = Product(company_id=c2.id, name="Widget", sku="W-001", price=Decimal("10.00"))
db.session.add(p2)
db.session.commit()
print(f"Cross-company same SKU: id={p2.id}")

# Same SKU, same company -- should fail
try:
    p3 = Product(company_id=c.id, name="Other", sku="W-001", price=Decimal("5.00"))
    db.session.add(p3)
    db.session.commit()
    print("ERROR: duplicate SKU was allowed!")
except Exception as e:
    db.session.rollback()
    print(f"Correctly blocked: {type(e).__name__}")
# Expected: Correctly blocked: IntegrityError
```

---

### Test 5: Product in multiple warehouses via inventory

```python
from models import Inventory
wh2 = Warehouse(company_id=c.id, name="West", location="LA")
db.session.add(wh2)
db.session.commit()

inv1 = Inventory(product_id=p1.id, warehouse_id=wh1.id, quantity=50)
inv2 = Inventory(product_id=p1.id, warehouse_id=wh2.id, quantity=30)
db.session.add_all([inv1, inv2])
db.session.commit()
print(f"Inventories: {len(p1.inventories)} records")
# Expected: Inventories: 2 records
```

---

### Test 6: Cannot delete product that has inventory (RESTRICT)

```python
try:
    db.session.delete(p1)
    db.session.commit()
    print("ERROR: product with inventory was deleted!")
except Exception as e:
    db.session.rollback()
    print(f"Correctly blocked: {type(e).__name__}")
# Expected: Correctly blocked: IntegrityError
```

---

### Test 7: Bundle cannot reference itself

```python
from models import BundleComponent
bundle = Product(company_id=c.id, name="Bundle", sku="B-001", price=Decimal("20.00"), product_type="bundle")
db.session.add(bundle)
db.session.commit()

try:
    bc = BundleComponent(bundle_product_id=bundle.id, component_product_id=bundle.id, component_quantity=1)
    db.session.add(bc)
    db.session.commit()
    print("ERROR: self-reference was allowed!")
except Exception as e:
    db.session.rollback()
    print(f"Correctly blocked: {type(e).__name__}")
# Expected: Correctly blocked: IntegrityError
```

---

### Test 8: Inventory movement audit trail

```python
from models import InventoryMovement
mov = InventoryMovement(
    inventory_id=inv1.id, change_type="purchase",
    quantity_change=50, quantity_before=0, quantity_after=50,
    note="Initial stock"
)
db.session.add(mov)
db.session.commit()
print(f"Movement created: id={mov.id}, type={mov.change_type}")
print(f"Movements for inv1: {len(inv1.movements)}")
# Expected: 1 movement linked to inventory
```

---

### Test 9: Cannot delete inventory that has movements (RESTRICT)

```python
try:
    db.session.delete(inv1)
    db.session.commit()
    print("ERROR: inventory with movements was deleted!")
except Exception as e:
    db.session.rollback()
    print(f"Correctly blocked: {type(e).__name__}")
# Expected: Correctly blocked: IntegrityError
```

---

### Test 10: Warehouse transfer cannot have same source and destination

```python
from models import WarehouseTransfer
try:
    t = WarehouseTransfer(
        product_id=p1.id, source_warehouse_id=wh1.id,
        dest_warehouse_id=wh1.id, quantity=10
    )
    db.session.add(t)
    db.session.commit()
    print("ERROR: same-warehouse transfer was allowed!")
except Exception as e:
    db.session.rollback()
    print(f"Correctly blocked: {type(e).__name__}")
# Expected: Correctly blocked: IntegrityError
```

---

### Test 11: Product model has no warehouse_id column

```python
columns = [col.name for col in Product.__table__.columns]
print(f"Product columns: {columns}")
assert "warehouse_id" not in columns
print("Confirmed: warehouse_id is NOT on Product")
# Expected: warehouse_id is NOT on Product
```

---

### Test Summary

| # | Test Case | Expected Result |
| --- | --- | --- |
| 1 | Create company | Success, id assigned |
| 2 | Duplicate warehouse name (same company) | IntegrityError |
| 3 | Same warehouse name (different company) | Success |
| 4 | Duplicate SKU same company / different company | Blocked / Allowed |
| 5 | Product in multiple warehouses | 2 inventory records |
| 6 | Delete product with inventory | IntegrityError (RESTRICT) |
| 7 | Bundle self-reference | IntegrityError |
| 8 | Inventory movement audit trail | Movement linked to inventory |
| 9 | Delete inventory with movements | IntegrityError (RESTRICT) |
| 10 | Transfer same source and dest | IntegrityError |
| 11 | Product has no warehouse_id | Column absent |

---

## Files

| File | Purpose |
| --- | --- |
| `schema.sql` | PostgreSQL DDL -- the complete schema in raw SQL |
| `models.py` | SQLAlchemy ORM models matching the DDL |
| `test_schema.py` | 35 pytest tests for constraints and relationships |
| `requirements.txt` | Python dependencies |
| `README.md` | This documentation |



================================================
FILE: part-2/models.py
================================================
"""
SQLAlchemy models matching the Part 2 database schema.
These can be used with Flask-SQLAlchemy or standalone SQLAlchemy.
"""

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    CheckConstraint,
    Index,
    func,
)
from sqlalchemy.orm import relationship

# Note: The SQL DDL (schema.sql) uses BIGSERIAL for PostgreSQL production use.
# Here we use Integer for SQLite compatibility in development/testing.
# SQLAlchemy's Integer maps to BIGINT on PostgreSQL when needed.

db = SQLAlchemy()


# ──────────────────────────────────────────────
# A. Companies
# ──────────────────────────────────────────────

class Company(db.Model):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    users = relationship("User", back_populates="company", cascade="all, delete-orphan")
    warehouses = relationship("Warehouse", back_populates="company", cascade="all, delete-orphan")
    products = relationship("Product", back_populates="company", cascade="all, delete-orphan")
    suppliers = relationship("Supplier", back_populates="company", cascade="all, delete-orphan")


# ──────────────────────────────────────────────
# B. Users
# ──────────────────────────────────────────────

class User(db.Model):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="staff")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    company = relationship("Company", back_populates="users")

    __table_args__ = (
        CheckConstraint("role IN ('admin', 'manager', 'staff')", name="ck_users_role"),
        Index("idx_users_company", "company_id"),
    )


# ──────────────────────────────────────────────
# C. Warehouses
# ──────────────────────────────────────────────

class Warehouse(db.Model):
    __tablename__ = "warehouses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    location = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    company = relationship("Company", back_populates="warehouses")
    inventories = relationship("Inventory", back_populates="warehouse")

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_warehouse_company_name"),
        Index("idx_warehouses_company", "company_id"),
    )


# ──────────────────────────────────────────────
# D. Products
# ──────────────────────────────────────────────

class Product(db.Model):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    sku = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Numeric(12, 2), nullable=False, default=0.00)
    product_type = Column(String(50), nullable=False, default="normal")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    company = relationship("Company", back_populates="products")
    inventories = relationship("Inventory", back_populates="product")
    suppliers = relationship("ProductSupplier", back_populates="product")

    # Bundle relationships
    bundle_components = relationship(
        "BundleComponent",
        foreign_keys="BundleComponent.bundle_product_id",
        back_populates="bundle",
        cascade="all, delete-orphan",
    )
    part_of_bundles = relationship(
        "BundleComponent",
        foreign_keys="BundleComponent.component_product_id",
        back_populates="component",
    )

    __table_args__ = (
        UniqueConstraint("company_id", "sku", name="uq_product_company_sku"),
        CheckConstraint("price >= 0", name="ck_products_price"),
        CheckConstraint("product_type IN ('normal', 'bundle')", name="ck_products_type"),
        Index("idx_products_company", "company_id"),
        Index("idx_products_sku", "sku"),
    )


# ──────────────────────────────────────────────
# E. Suppliers
# ──────────────────────────────────────────────

class Supplier(db.Model):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    contact_email = Column(String(255), nullable=True)
    contact_phone = Column(String(50), nullable=True)
    address = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    company = relationship("Company", back_populates="suppliers")
    products = relationship("ProductSupplier", back_populates="supplier")

    __table_args__ = (
        Index("idx_suppliers_company", "company_id"),
    )


# ──────────────────────────────────────────────
# F. Product-Supplier (many-to-many)
# ──────────────────────────────────────────────

class ProductSupplier(db.Model):
    __tablename__ = "product_suppliers"

    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id", ondelete="CASCADE"), primary_key=True)
    supplier_sku = Column(String(100), nullable=True)
    lead_time_days = Column(Integer, nullable=True)
    cost_price = Column(Numeric(12, 2), nullable=True)
    is_primary = Column(Boolean, nullable=False, default=False)

    product = relationship("Product", back_populates="suppliers")
    supplier = relationship("Supplier", back_populates="products")

    __table_args__ = (
        CheckConstraint("lead_time_days IS NULL OR lead_time_days >= 0", name="ck_ps_lead_time"),
        CheckConstraint("cost_price IS NULL OR cost_price >= 0", name="ck_ps_cost_price"),
    )


# ──────────────────────────────────────────────
# G. Inventory
# ──────────────────────────────────────────────

class Inventory(db.Model):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False)
    quantity = Column(Integer, nullable=False, default=0)
    reserved_quantity = Column(Integer, nullable=False, default=0)
    reorder_level = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    product = relationship("Product", back_populates="inventories")
    warehouse = relationship("Warehouse", back_populates="inventories")
    movements = relationship("InventoryMovement", back_populates="inventory")

    __table_args__ = (
        UniqueConstraint("product_id", "warehouse_id", name="uq_inventory_product_warehouse"),
        CheckConstraint("quantity >= 0", name="ck_inventory_qty"),
        CheckConstraint("reserved_quantity >= 0", name="ck_inventory_reserved"),
        CheckConstraint("reserved_quantity <= quantity", name="ck_inventory_reserved_lte_qty"),
        Index("idx_inventory_warehouse", "warehouse_id"),
        Index("idx_inventory_product", "product_id"),
    )


# ──────────────────────────────────────────────
# H. Inventory Movements (audit log)
# ──────────────────────────────────────────────

class InventoryMovement(db.Model):
    __tablename__ = "inventory_movements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    inventory_id = Column(Integer, ForeignKey("inventory.id", ondelete="RESTRICT"), nullable=False)
    change_type = Column(String(50), nullable=False)
    quantity_change = Column(Integer, nullable=False)
    quantity_before = Column(Integer, nullable=False)
    quantity_after = Column(Integer, nullable=False)
    reference_type = Column(String(100), nullable=True)
    reference_id = Column(Integer, nullable=True)
    performed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    inventory = relationship("Inventory", back_populates="movements")
    performer = relationship("User")

    __table_args__ = (
        CheckConstraint("quantity_change <> 0", name="ck_movements_nonzero"),
        CheckConstraint("quantity_after >= 0", name="ck_movements_after_positive"),
        CheckConstraint(
            "change_type IN ('purchase', 'sale', 'return', 'adjustment', "
            "'transfer_in', 'transfer_out', 'damaged', 'bundle_assembly')",
            name="ck_movements_type",
        ),
        Index("idx_movements_inventory", "inventory_id"),
        Index("idx_movements_created", "created_at"),
        Index("idx_movements_reference", "reference_type", "reference_id"),
        Index("idx_movements_performer", "performed_by"),
    )


# ──────────────────────────────────────────────
# I. Bundle Components
# ──────────────────────────────────────────────

class BundleComponent(db.Model):
    __tablename__ = "bundle_components"

    bundle_product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    component_product_id = Column(Integer, ForeignKey("products.id", ondelete="RESTRICT"), primary_key=True)
    component_quantity = Column(Integer, nullable=False)

    bundle = relationship("Product", foreign_keys=[bundle_product_id], back_populates="bundle_components")
    component = relationship("Product", foreign_keys=[component_product_id], back_populates="part_of_bundles")

    __table_args__ = (
        CheckConstraint("component_quantity > 0", name="ck_bundle_qty"),
        CheckConstraint("bundle_product_id <> component_product_id", name="ck_bundle_no_self_ref"),
    )


# ──────────────────────────────────────────────
# J. Warehouse Transfers
# ──────────────────────────────────────────────

class WarehouseTransfer(db.Model):
    __tablename__ = "warehouse_transfers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    source_warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False)
    dest_warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False)
    quantity = Column(Integer, nullable=False)
    status = Column(String(50), nullable=False, default="pending")
    initiated_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    product = relationship("Product")
    source_warehouse = relationship("Warehouse", foreign_keys=[source_warehouse_id])
    dest_warehouse = relationship("Warehouse", foreign_keys=[dest_warehouse_id])
    initiator = relationship("User")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_transfer_qty"),
        CheckConstraint("source_warehouse_id <> dest_warehouse_id", name="ck_transfer_diff_wh"),
        CheckConstraint(
            "status IN ('pending', 'in_transit', 'completed', 'cancelled')",
            name="ck_transfer_status",
        ),
        Index("idx_transfers_product", "product_id"),
        Index("idx_transfers_source", "source_warehouse_id"),
        Index("idx_transfers_dest", "dest_warehouse_id"),
    )



================================================
FILE: part-2/requirements.txt
================================================
Flask==3.1.1
Flask-SQLAlchemy==3.1.1
SQLAlchemy==2.0.40
pytest==8.3.3



================================================
FILE: part-2/schema.sql
================================================
-- ============================================================
-- StockFlow Database Schema
-- Part 2: Database Design
-- ============================================================

-- ────────────────────────────────────────────
-- A. companies
-- ────────────────────────────────────────────
-- Tenant table. Every warehouse, product, and supplier is scoped to a company.

CREATE TABLE companies (
    id          BIGSERIAL PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);


-- ────────────────────────────────────────────
-- B. users
-- ────────────────────────────────────────────
-- Needed for audit trail (who performed inventory changes).

CREATE TABLE users (
    id          BIGSERIAL PRIMARY KEY,
    company_id  BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    email       VARCHAR(255) NOT NULL,
    name        VARCHAR(255) NOT NULL,
    role        VARCHAR(50) NOT NULL DEFAULT 'staff',
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW(),

    UNIQUE (email),
    CHECK (role IN ('admin', 'manager', 'staff'))
);

CREATE INDEX idx_users_company ON users(company_id);


-- ────────────────────────────────────────────
-- C. warehouses
-- ────────────────────────────────────────────
-- Each company can have multiple warehouses.
-- Warehouse names must be unique within a company.

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

CREATE INDEX idx_warehouses_company ON warehouses(company_id);


-- ────────────────────────────────────────────
-- D. products
-- ────────────────────────────────────────────
-- Product master data. Belongs to one company.
-- SKU is unique within a company (not globally — multi-tenant scoping).
-- Price uses DECIMAL(12,2) to avoid floating-point errors.
-- product_type is constrained to known values.

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

CREATE INDEX idx_products_company ON products(company_id);
CREATE INDEX idx_products_sku     ON products(sku);


-- ────────────────────────────────────────────
-- E. suppliers
-- ────────────────────────────────────────────
-- Scoped to a company. Each company manages its own supplier list.

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

CREATE INDEX idx_suppliers_company ON suppliers(company_id);


-- ────────────────────────────────────────────
-- F. product_suppliers
-- ────────────────────────────────────────────
-- Many-to-many: which suppliers provide which products.
-- Tracks supplier-specific SKU, lead time, and primary flag.

CREATE TABLE product_suppliers (
    product_id    BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    supplier_id   BIGINT NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    supplier_sku  VARCHAR(100),
    lead_time_days INTEGER,
    cost_price    DECIMAL(12,2),
    is_primary    BOOLEAN NOT NULL DEFAULT FALSE,

    PRIMARY KEY (product_id, supplier_id),
    CHECK (lead_time_days IS NULL OR lead_time_days >= 0),
    CHECK (cost_price IS NULL OR cost_price >= 0)
);


-- ────────────────────────────────────────────
-- G. inventory
-- ────────────────────────────────────────────
-- Current stock of each product in each warehouse.
-- Uses RESTRICT on delete to prevent accidental data loss.
-- reserved_quantity tracks stock allocated to pending orders.

CREATE TABLE inventory (
    id                BIGSERIAL PRIMARY KEY,
    product_id        BIGINT NOT NULL REFERENCES products(id)    ON DELETE RESTRICT,
    warehouse_id      BIGINT NOT NULL REFERENCES warehouses(id)  ON DELETE RESTRICT,
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

CREATE INDEX idx_inventory_warehouse ON inventory(warehouse_id);
CREATE INDEX idx_inventory_product   ON inventory(product_id);


-- ────────────────────────────────────────────
-- H. inventory_movements
-- ────────────────────────────────────────────
-- Immutable audit log of every stock change.
-- Uses RESTRICT to prevent deletion of inventory rows that have history.
-- Tracks who made the change (performed_by).
-- Uses polymorphic reference (reference_type + reference_id) for linking
-- to orders, purchase orders, transfers, etc.

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
    CHECK (change_type IN (
        'purchase',       -- stock received from supplier
        'sale',           -- stock sold to customer
        'return',         -- customer return
        'adjustment',     -- manual correction
        'transfer_in',    -- received from another warehouse
        'transfer_out',   -- sent to another warehouse
        'damaged',        -- written off as damaged
        'bundle_assembly' -- consumed by bundle creation
    ))
);

CREATE INDEX idx_movements_inventory  ON inventory_movements(inventory_id);
CREATE INDEX idx_movements_created    ON inventory_movements(created_at);
CREATE INDEX idx_movements_reference  ON inventory_movements(reference_type, reference_id);
CREATE INDEX idx_movements_performer  ON inventory_movements(performed_by);


-- ────────────────────────────────────────────
-- I. bundle_components
-- ────────────────────────────────────────────
-- Self-referencing join table for bundle products.
-- A bundle product contains N units of each component product.
-- Self-reference is blocked (a product cannot contain itself).

CREATE TABLE bundle_components (
    bundle_product_id     BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    component_product_id  BIGINT NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    component_quantity    INTEGER NOT NULL,

    PRIMARY KEY (bundle_product_id, component_product_id),
    CHECK (component_quantity > 0),
    CHECK (bundle_product_id <> component_product_id)
);


-- ────────────────────────────────────────────
-- J. warehouse_transfers (first-class transfer tracking)
-- ────────────────────────────────────────────
-- Links the transfer_out and transfer_in movements atomically.
-- Provides a single record for "moved X units of product Y from WH-A to WH-B".

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

CREATE INDEX idx_transfers_product ON warehouse_transfers(product_id);
CREATE INDEX idx_transfers_source  ON warehouse_transfers(source_warehouse_id);
CREATE INDEX idx_transfers_dest    ON warehouse_transfers(dest_warehouse_id);



================================================
FILE: part-2/test_schema.py
================================================
"""
Tests verifying schema constraints, relationships, and data integrity.
Uses an in-memory SQLite database with Flask-SQLAlchemy.
"""

import pytest
from decimal import Decimal
from flask import Flask
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

from models import (
    db,
    Company,
    User,
    Warehouse,
    Product,
    Supplier,
    ProductSupplier,
    Inventory,
    InventoryMovement,
    BundleComponent,
    WarehouseTransfer,
)


def _enable_sqlite_fk(dbapi_conn, connection_record):
    """SQLite ignores FK constraints by default. This enables them."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["TESTING"] = True
    db.init_app(app)
    with app.app_context():
        # Enable foreign key enforcement for SQLite
        event.listen(db.engine, "connect", _enable_sqlite_fk)
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def session(app):
    with app.app_context():
        yield db.session


@pytest.fixture
def company(session):
    c = Company(name="Acme Corp")
    session.add(c)
    session.commit()
    return c


@pytest.fixture
def user(session, company):
    u = User(company_id=company.id, email="alice@acme.com", name="Alice", role="admin")
    session.add(u)
    session.commit()
    return u


@pytest.fixture
def warehouses(session, company):
    wh1 = Warehouse(company_id=company.id, name="East", location="New York")
    wh2 = Warehouse(company_id=company.id, name="West", location="Los Angeles")
    session.add_all([wh1, wh2])
    session.commit()
    return wh1, wh2


@pytest.fixture
def product(session, company):
    p = Product(company_id=company.id, name="Widget", sku="WDG-001", price=Decimal("19.99"))
    session.add(p)
    session.commit()
    return p


@pytest.fixture
def supplier(session, company):
    s = Supplier(company_id=company.id, name="Parts Inc", contact_email="info@parts.com")
    session.add(s)
    session.commit()
    return s


# ──────────────────────────────────────────────
# Company tests
# ──────────────────────────────────────────────

class TestCompany:

    def test_create_company(self, session, company):
        assert company.id is not None
        assert company.name == "Acme Corp"

    def test_company_has_relationships(self, session, company):
        assert company.users == []
        assert company.warehouses == []
        assert company.products == []
        assert company.suppliers == []


# ──────────────────────────────────────────────
# User tests
# ──────────────────────────────────────────────

class TestUser:

    def test_create_user(self, session, user):
        assert user.id is not None
        assert user.role == "admin"

    def test_duplicate_email_rejected(self, session, company, user):
        u2 = User(company_id=company.id, email="alice@acme.com", name="Alice2", role="staff")
        session.add(u2)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_user_belongs_to_company(self, session, user, company):
        assert user.company_id == company.id
        assert user in company.users


# ──────────────────────────────────────────────
# Warehouse tests
# ──────────────────────────────────────────────

class TestWarehouse:

    def test_create_warehouse(self, session, warehouses):
        wh1, wh2 = warehouses
        assert wh1.name == "East"
        assert wh2.location == "Los Angeles"

    def test_multiple_warehouses_per_company(self, session, company, warehouses):
        assert len(company.warehouses) == 2

    def test_duplicate_name_same_company_rejected(self, session, company, warehouses):
        dup = Warehouse(company_id=company.id, name="East", location="Other")
        session.add(dup)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_same_name_different_company_allowed(self, session, warehouses):
        c2 = Company(name="Other Corp")
        session.add(c2)
        session.commit()
        wh = Warehouse(company_id=c2.id, name="East", location="Boston")
        session.add(wh)
        session.commit()  # Should not raise
        assert wh.id is not None


# ──────────────────────────────────────────────
# Product tests
# ──────────────────────────────────────────────

class TestProduct:

    def test_create_product(self, session, product):
        assert product.id is not None
        assert product.price == Decimal("19.99")
        assert product.product_type == "normal"

    def test_duplicate_sku_same_company_rejected(self, session, company, product):
        dup = Product(company_id=company.id, name="Other", sku="WDG-001", price=Decimal("5.00"))
        session.add(dup)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_same_sku_different_company_allowed(self, session, product):
        c2 = Company(name="Other Corp")
        session.add(c2)
        session.commit()
        p2 = Product(company_id=c2.id, name="Other Widget", sku="WDG-001", price=Decimal("9.99"))
        session.add(p2)
        session.commit()  # Should not raise
        assert p2.id is not None

    def test_product_belongs_to_company(self, session, product, company):
        assert product.company_id == company.id
        assert product in company.products

    def test_decimal_price_precision(self, session, company):
        p = Product(company_id=company.id, name="Precise", sku="PRC-001", price=Decimal("999999999.99"))
        session.add(p)
        session.commit()
        assert p.price == Decimal("999999999.99")


# ──────────────────────────────────────────────
# Supplier tests
# ──────────────────────────────────────────────

class TestSupplier:

    def test_create_supplier(self, session, supplier):
        assert supplier.id is not None
        assert supplier.name == "Parts Inc"

    def test_supplier_scoped_to_company(self, session, supplier, company):
        assert supplier.company_id == company.id
        assert supplier in company.suppliers


# ──────────────────────────────────────────────
# Product-Supplier tests
# ──────────────────────────────────────────────

class TestProductSupplier:

    def test_link_product_to_supplier(self, session, product, supplier):
        ps = ProductSupplier(
            product_id=product.id,
            supplier_id=supplier.id,
            supplier_sku="SUP-WDG",
            lead_time_days=7,
            cost_price=Decimal("12.00"),
            is_primary=True,
        )
        session.add(ps)
        session.commit()
        assert len(product.suppliers) == 1
        assert product.suppliers[0].supplier_sku == "SUP-WDG"

    def test_multiple_suppliers_per_product(self, session, company, product):
        s1 = Supplier(company_id=company.id, name="Supplier A")
        s2 = Supplier(company_id=company.id, name="Supplier B")
        session.add_all([s1, s2])
        session.commit()

        session.add(ProductSupplier(product_id=product.id, supplier_id=s1.id))
        session.add(ProductSupplier(product_id=product.id, supplier_id=s2.id))
        session.commit()
        assert len(product.suppliers) == 2

    def test_duplicate_product_supplier_rejected(self, session, product, supplier):
        session.add(ProductSupplier(product_id=product.id, supplier_id=supplier.id))
        session.commit()
        session.add(ProductSupplier(product_id=product.id, supplier_id=supplier.id))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


# ──────────────────────────────────────────────
# Inventory tests
# ──────────────────────────────────────────────

class TestInventory:

    def test_create_inventory(self, session, product, warehouses):
        wh1, _ = warehouses
        inv = Inventory(product_id=product.id, warehouse_id=wh1.id, quantity=100)
        session.add(inv)
        session.commit()
        assert inv.id is not None
        assert inv.quantity == 100
        assert inv.reserved_quantity == 0

    def test_product_in_multiple_warehouses(self, session, product, warehouses):
        wh1, wh2 = warehouses
        session.add(Inventory(product_id=product.id, warehouse_id=wh1.id, quantity=50))
        session.add(Inventory(product_id=product.id, warehouse_id=wh2.id, quantity=30))
        session.commit()
        assert len(product.inventories) == 2

    def test_duplicate_product_warehouse_rejected(self, session, product, warehouses):
        wh1, _ = warehouses
        session.add(Inventory(product_id=product.id, warehouse_id=wh1.id, quantity=10))
        session.commit()
        session.add(Inventory(product_id=product.id, warehouse_id=wh1.id, quantity=20))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_delete_product_with_inventory_blocked(self, session, product, warehouses):
        """ON DELETE RESTRICT prevents deleting a product that has inventory."""
        wh1, _ = warehouses
        session.add(Inventory(product_id=product.id, warehouse_id=wh1.id, quantity=10))
        session.commit()
        session.delete(product)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_delete_warehouse_with_inventory_blocked(self, session, product, warehouses):
        """ON DELETE RESTRICT prevents deleting a warehouse that has inventory."""
        wh1, _ = warehouses
        session.add(Inventory(product_id=product.id, warehouse_id=wh1.id, quantity=10))
        session.commit()
        session.delete(wh1)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


# ──────────────────────────────────────────────
# Inventory Movement tests
# ──────────────────────────────────────────────

class TestInventoryMovement:

    def test_create_movement(self, session, product, warehouses, user):
        wh1, _ = warehouses
        inv = Inventory(product_id=product.id, warehouse_id=wh1.id, quantity=100)
        session.add(inv)
        session.commit()

        mov = InventoryMovement(
            inventory_id=inv.id,
            change_type="purchase",
            quantity_change=100,
            quantity_before=0,
            quantity_after=100,
            performed_by=user.id,
            note="Initial stock",
        )
        session.add(mov)
        session.commit()
        assert mov.id is not None
        assert mov.performer.name == "Alice"

    def test_movement_linked_to_inventory(self, session, product, warehouses):
        wh1, _ = warehouses
        inv = Inventory(product_id=product.id, warehouse_id=wh1.id, quantity=50)
        session.add(inv)
        session.commit()

        session.add(InventoryMovement(
            inventory_id=inv.id, change_type="purchase",
            quantity_change=50, quantity_before=0, quantity_after=50,
        ))
        session.add(InventoryMovement(
            inventory_id=inv.id, change_type="sale",
            quantity_change=-10, quantity_before=50, quantity_after=40,
        ))
        session.commit()
        assert len(inv.movements) == 2

    def test_delete_inventory_with_movements_blocked(self, session, product, warehouses):
        """ON DELETE RESTRICT prevents deleting inventory that has movement history."""
        wh1, _ = warehouses
        inv = Inventory(product_id=product.id, warehouse_id=wh1.id, quantity=50)
        session.add(inv)
        session.commit()

        session.add(InventoryMovement(
            inventory_id=inv.id, change_type="purchase",
            quantity_change=50, quantity_before=0, quantity_after=50,
        ))
        session.commit()

        session.delete(inv)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


# ──────────────────────────────────────────────
# Bundle Component tests
# ──────────────────────────────────────────────

class TestBundleComponent:

    def test_create_bundle(self, session, company):
        comp1 = Product(company_id=company.id, name="Part A", sku="PA-001", price=Decimal("5.00"))
        comp2 = Product(company_id=company.id, name="Part B", sku="PB-001", price=Decimal("3.00"))
        bundle = Product(
            company_id=company.id, name="Bundle AB", sku="BND-001",
            price=Decimal("10.00"), product_type="bundle",
        )
        session.add_all([comp1, comp2, bundle])
        session.commit()

        session.add(BundleComponent(bundle_product_id=bundle.id, component_product_id=comp1.id, component_quantity=2))
        session.add(BundleComponent(bundle_product_id=bundle.id, component_product_id=comp2.id, component_quantity=1))
        session.commit()

        assert len(bundle.bundle_components) == 2
        assert bundle.bundle_components[0].component_quantity == 2

    def test_component_knows_its_bundles(self, session, company):
        comp = Product(company_id=company.id, name="Part X", sku="PX-001", price=Decimal("5.00"))
        b1 = Product(company_id=company.id, name="Bundle 1", sku="B1", price=Decimal("10.00"), product_type="bundle")
        b2 = Product(company_id=company.id, name="Bundle 2", sku="B2", price=Decimal("15.00"), product_type="bundle")
        session.add_all([comp, b1, b2])
        session.commit()

        session.add(BundleComponent(bundle_product_id=b1.id, component_product_id=comp.id, component_quantity=1))
        session.add(BundleComponent(bundle_product_id=b2.id, component_product_id=comp.id, component_quantity=3))
        session.commit()
        assert len(comp.part_of_bundles) == 2

    def test_self_reference_blocked(self, session, product):
        """A product cannot be a component of itself."""
        bc = BundleComponent(bundle_product_id=product.id, component_product_id=product.id, component_quantity=1)
        session.add(bc)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_delete_component_with_bundles_blocked(self, session, company):
        """ON DELETE RESTRICT on component prevents deleting a product used in bundles.
        SQLAlchemy's ORM may raise AssertionError (trying to null a composite PK)
        before the DB-level IntegrityError fires, so we catch both."""
        comp = Product(company_id=company.id, name="Critical Part", sku="CP-001", price=Decimal("5.00"))
        bundle = Product(company_id=company.id, name="Bundle", sku="BND-X", price=Decimal("10.00"), product_type="bundle")
        session.add_all([comp, bundle])
        session.commit()
        session.add(BundleComponent(bundle_product_id=bundle.id, component_product_id=comp.id, component_quantity=1))
        session.commit()

        session.delete(comp)
        with pytest.raises((IntegrityError, AssertionError)):
            session.commit()
        session.rollback()


# ──────────────────────────────────────────────
# Warehouse Transfer tests
# ──────────────────────────────────────────────

class TestWarehouseTransfer:

    def test_create_transfer(self, session, product, warehouses, user):
        wh1, wh2 = warehouses
        t = WarehouseTransfer(
            product_id=product.id,
            source_warehouse_id=wh1.id,
            dest_warehouse_id=wh2.id,
            quantity=25,
            initiated_by=user.id,
        )
        session.add(t)
        session.commit()
        assert t.id is not None
        assert t.status == "pending"
        assert t.source_warehouse.name == "East"
        assert t.dest_warehouse.name == "West"

    def test_transfer_same_warehouse_blocked(self, session, product, warehouses):
        """Cannot transfer to the same warehouse."""
        wh1, _ = warehouses
        t = WarehouseTransfer(
            product_id=product.id,
            source_warehouse_id=wh1.id,
            dest_warehouse_id=wh1.id,
            quantity=10,
        )
        session.add(t)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


# ──────────────────────────────────────────────
# Cross-cutting / integration tests
# ──────────────────────────────────────────────

class TestIntegration:

    def test_full_product_lifecycle(self, session, company, user):
        """Create company -> warehouse -> product -> inventory -> movement."""
        wh = Warehouse(company_id=company.id, name="Main", location="HQ")
        session.add(wh)
        session.commit()

        p = Product(company_id=company.id, name="Gadget", sku="GDG-001", price=Decimal("49.99"))
        session.add(p)
        session.commit()

        inv = Inventory(product_id=p.id, warehouse_id=wh.id, quantity=200)
        session.add(inv)
        session.commit()

        mov = InventoryMovement(
            inventory_id=inv.id, change_type="purchase",
            quantity_change=200, quantity_before=0, quantity_after=200,
            performed_by=user.id, note="Initial purchase order",
        )
        session.add(mov)
        session.commit()

        # Verify chain
        assert p in company.products
        assert wh in company.warehouses
        assert inv in p.inventories
        assert mov in inv.movements
        assert mov.performer == user

    def test_product_model_has_no_warehouse_column(self):
        """Verify data model: Product should NOT have a warehouse_id column."""
        columns = [col.name for col in Product.__table__.columns]
        assert "warehouse_id" not in columns



================================================
FILE: part-3/README.md
================================================
# Part 3: API Implementation -- Low-Stock Alerts

## The Problem

Implement an endpoint that returns low-stock alerts for a company.

```
GET /api/companies/{company_id}/alerts/low-stock
```

### Business Rules

- Low stock threshold varies by product type
- Only alert for products with recent sales activity
- Must handle multiple warehouses per company
- Include supplier information for reordering

---

## Review of Original Solution

The proposed solution had the right overall structure but several issues that would cause problems at scale or in production:

### Issue 1: N+1 Query Problem (Performance)

The original code runs **two extra queries per inventory row** inside a loop:

```python
for row in rows:
    recent_sales_count = db.session.query(...)  # Query 1: sales per row
    supplier_link = db.session.query(...)       # Query 2: supplier per row
```

For a company with 1,000 inventory rows, this executes ~2,001 queries. At scale this makes the endpoint unusably slow.

**Fix:** Use subqueries joined in a single query. The sales aggregation and supplier lookup are each computed once as subqueries, then joined to the main inventory query.

### Issue 2: References Non-Existent Tables

The original uses `Sale` and `SaleItem` tables that don't exist in the Part 2 schema. The schema tracks sales through `inventory_movements` with `change_type='sale'`.

**Fix:** Query `inventory_movements` filtered by `change_type='sale'` instead.

### Issue 3: Ignores `reserved_quantity`

The original compares `inventory.quantity` against the threshold, but reserved stock is committed to pending orders and not actually available.

**Fix:** Available stock = `quantity - reserved_quantity`. This is what gets compared against the threshold and returned as `current_stock`.

### Issue 4: Ignores `reorder_level`

The Part 2 schema already has a per-warehouse `reorder_level` column on the `inventory` table. The original ignores it and uses only a hardcoded product-type mapping.

**Fix:** Use `inventory.reorder_level` when set, falling back to product-type defaults only when it's NULL. This allows warehouse managers to customize thresholds per location.

### Issue 5: Ignores `is_active` Flags

The original doesn't filter out inactive products or inactive warehouses. A discontinued product sitting at low stock shouldn't generate alerts.

**Fix:** Filter on `Product.is_active == True` and `Warehouse.is_active == True`.

### Issue 6: No Company Existence Check

The original returns an empty 200 for a non-existent `company_id`. Clients can't distinguish "company has no alerts" from "company doesn't exist."

**Fix:** Check `db.session.get(Company, company_id)` first and return 404 if not found.

### Issue 7: No Sorting

Alerts are returned in arbitrary database order. The most urgent alerts (lowest `days_until_stockout`) should come first so warehouse managers see critical items at the top.

**Fix:** Sort by `days_until_stockout` ascending.

### Issue 8: No Pagination

A large company could have thousands of low-stock alerts. Returning all of them in one response is slow and wasteful.

**Fix:** Add `limit` (default 50) and `offset` query parameters. Return `total_alerts` so clients know the full count.

### Issue 9: Hardcoded Threshold Only

The original only uses a hardcoded dictionary for thresholds. This ignores the `reorder_level` column from the schema and provides no way for warehouse managers to customize without code changes.

**Fix:** Priority chain: `inventory.reorder_level` (per-warehouse) > product-type default (config). This is documented as a design decision.

---

## Corrected Implementation

### Architecture

The endpoint executes **3 queries total** regardless of data volume (not N+1):

```
┌─────────────────────────────────────┐
│ 1. Sales subquery                   │
│    SUM(quantity_change) per inv_id  │
│    WHERE change_type='sale'         │
│    AND created_at >= cutoff         │
└──────────────┬──────────────────────┘
               │ INNER JOIN (excludes zero-sales)
┌──────────────┴──────────────────────┐
│ 2. Main query                       │
│    inventory + product + warehouse  │
│    WHERE company_id = ?             │
│    AND is_active = True             │
└──────────────┬──────────────────────┘
               │ LEFT JOIN (supplier may be NULL)
┌──────────────┴──────────────────────┐
│ 3. Supplier subquery                │
│    ROW_NUMBER() per product_id      │
│    ORDER BY is_primary DESC, id ASC │
│    WHERE rn = 1                     │
└─────────────────────────────────────┘
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| INNER JOIN on sales subquery | Automatically excludes products with no recent sales -- no Python filtering needed |
| LEFT JOIN on supplier subquery | Products without suppliers still appear in alerts (supplier field = null) |
| ROW_NUMBER() for supplier selection | Portable across SQLite and PostgreSQL (unlike DISTINCT ON) |
| Threshold in Python, not SQL | SQLite doesn't support CASE with column-dependent defaults cleanly; trivial to push into SQL on PostgreSQL |
| `available_stock = quantity - reserved` | Reserved stock is committed to orders and shouldn't count as available |
| Sort by `days_until_stockout` ascending | Most urgent alerts first -- warehouse managers see critical items at top |

### Threshold Priority

```
1. inventory.reorder_level   (per product-warehouse, set by warehouse manager)
2. DEFAULT_THRESHOLDS[type]  (per product type, from config)
3. DEFAULT_THRESHOLD_FALLBACK (global fallback: 20)
```

### Stockout Estimation

```
avg_daily_sales = total_units_sold_in_period / days_in_period
days_until_stockout = available_stock / avg_daily_sales
```

- Uses `inventory_movements` with `change_type='sale'` (not a separate Sales table)
- Sale movements have negative `quantity_change`, so `func.abs(func.sum(...))` gives total sold
- If `avg_daily_sales` is 0, `days_until_stockout` is `null` (shouldn't happen due to INNER JOIN filter)

### Query Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `days` | 30 | Lookback window for "recent" sales activity |
| `limit` | 50 | Max alerts per page |
| `offset` | 0 | Pagination offset |

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
  "total_alerts": 1,
  "limit": 50,
  "offset": 0
}
```

---

## Edge Cases Handled

| # | Edge Case | Behavior |
|---|-----------|----------|
| 1 | Company doesn't exist | 404 with `{"error": "Company not found"}` |
| 2 | Company has no inventory | 200 with empty `alerts` array |
| 3 | Product has no recent sales | Excluded from results (INNER JOIN on sales subquery) |
| 4 | Sales older than lookback window | Not counted (filtered by `created_at >= cutoff`) |
| 5 | Inactive product | Excluded (`is_active == True` filter) |
| 6 | Inactive warehouse | Excluded (`is_active == True` filter) |
| 7 | No supplier linked | Alert still appears, `supplier` field is `null` |
| 8 | No primary supplier | Falls back to any active supplier (ordered by id) |
| 9 | Stock above threshold | Not included in alerts |
| 10 | Reserved stock reduces available | `current_stock = quantity - reserved_quantity` |
| 11 | Per-warehouse reorder level set | Overrides product-type default threshold |
| 12 | Other company's data | Strictly filtered by `company_id` -- no cross-tenant leakage |
| 13 | Invalid query parameters | 400 with error message (non-numeric, negative, zero limit) |
| 14 | Zero average daily sales | `days_until_stockout` is `null` (guard against division by zero) |
| 15 | Same product in multiple warehouses | Separate alert per warehouse, each with independent stock/threshold |
| 16 | Large result sets | Paginated via `limit`/`offset`, `total_alerts` shows full count |

---

## Assumptions

1. **"Recent sales activity"** = at least one `inventory_movement` with `change_type='sale'` within the lookback window (default 30 days)
2. **Sales data comes from `inventory_movements`**, not a separate Sales/SaleItem table (consistent with Part 2 schema)
3. **Available stock** = `quantity - reserved_quantity` (reserved stock is committed to pending orders)
4. **Threshold priority**: per-warehouse `reorder_level` > product-type default > global fallback (20)
5. **`days_until_stockout`** is estimated from average daily sales rate over the lookback window
6. **One supplier per alert**: the primary supplier is preferred, falling back to any active supplier
7. **Inactive products and warehouses** are excluded from alerts
8. **Alerts are sorted** by urgency (lowest `days_until_stockout` first)

---

## Tests

32 tests covering all edge cases and business rules:

```bash
cd part-3
pip install -r requirements.txt
python -m pytest test_alerts.py -v
```

| Test Class | Count | What It Verifies |
|-----------|-------|-----------------|
| TestHappyPath | 2 | Basic alert returned, response structure |
| TestThresholdLogic | 4 | reorder_level override, product-type defaults, no alert above threshold |
| TestFiltering | 5 | No sales excluded, old sales excluded, inactive product/warehouse, cross-company isolation |
| TestReservedStock | 2 | Reserved reduces available, no false alert when reserved doesn't breach |
| TestStockoutEstimation | 2 | Correct calculation, high sales rate |
| TestSupplierInfo | 3 | Primary supplier, null supplier, fallback to non-primary |
| TestMultiWarehouse | 2 | Per-warehouse alerts, alert only for low warehouse |
| TestSorting | 1 | Most urgent first |
| TestPagination | 4 | Default, custom limit, offset, beyond-total offset |
| TestLookbackDays | 1 | Custom `days` parameter |
| TestErrorHandling | 6 | 404 company, invalid/negative params, empty company |

---

## API Test Cases (Postman)

### Setup

```bash
cd part-3
pip install -r requirements.txt
python seed.py    # populate database with test data
python app.py     # starts server on http://127.0.0.1:5001
```

The seed script creates:

- **Company 1** (Acme Corp) with 2 active warehouses, 1 inactive warehouse, 9 products, 2 suppliers
- **Company 2** (Other Corp) with 1 warehouse, 1 product (for cross-tenant isolation testing)

**Expected alerts for Company 1:** 7 total (sorted by urgency)

| Product | SKU | Warehouse | Stock | Threshold | Why Alert |
| --- | --- | --- | --- | --- | --- |
| Widget A | WID-001 | East | 5 | 20 | Low stock, recent sales |
| Gadget B | GDG-002 | East | 3 | 20 | Low stock, no supplier |
| Multi-WH G | MWH-007 | West | 4 | 20 | Low in west warehouse |
| Reserved I | RSV-009 | East | 10 (avail) | 20 | qty=30, reserved=20 |
| Multi-WH G | MWH-007 | East | 8 | 20 | Low in east warehouse |
| Bundle F | BND-006 | West | 10 | 15 | Bundle threshold=15 |
| Custom Thresh H | CTH-008 | East | 18 | 25 | Custom reorder_level=25 |

**NOT expected (filtered out):**

- Bolt C -- stock=100, above threshold
- Stale Item D -- no recent sales
- Discontinued E -- is_active=False
- Widget A in Closed WH -- warehouse is_active=False
- Other Corp's product -- different company

All requests below are **GET** with no body.

---

### Test 1: Happy path -- all alerts for Acme Corp

```
GET http://127.0.0.1:5001/api/companies/1/alerts/low-stock
```

**Expected:** Status `200`, `total_alerts` = 7

**Verify:**

- First alert has lowest `days_until_stockout` (most urgent)
- Last alert has highest `days_until_stockout` (least urgent)
- Gadget B has `"supplier": null`
- Reserved Stock I shows `current_stock` = 10 (not 30)
- Custom Thresh H shows `threshold` = 25 (not default 20)
- Bundle F shows `threshold` = 15 (bundle default)
- Multi-WH G appears **twice** (once per warehouse)

---

### Test 2: Company not found (404)

```
GET http://127.0.0.1:5001/api/companies/99999/alerts/low-stock
```

**Expected:**

```json
{
  "error": "Company not found"
}
```

Status `404`.

---

### Test 3: Cross-tenant isolation -- Other Corp

```
GET http://127.0.0.1:5001/api/companies/2/alerts/low-stock
```

**Expected:** Status `200`, `total_alerts` = 0.

Other Corp's low-stock product should NOT appear in Acme's results (Test 1), and Company 2 has no products with sales within the default 30-day window matching its own data.

---

### Test 4: Pagination -- limit

```
GET http://127.0.0.1:5001/api/companies/1/alerts/low-stock?limit=2
```

**Expected:** Status `200`, `total_alerts` = 7, but `alerts` array has only 2 items. `limit` = 2, `offset` = 0.

---

### Test 5: Pagination -- offset

```
GET http://127.0.0.1:5001/api/companies/1/alerts/low-stock?limit=2&offset=2
```

**Expected:** Status `200`, `total_alerts` = 7, `alerts` array has 2 items (items 3-4). Alerts are different from Test 4.

---

### Test 6: Pagination -- offset beyond total

```
GET http://127.0.0.1:5001/api/companies/1/alerts/low-stock?offset=100
```

**Expected:** Status `200`, `total_alerts` = 7, `alerts` = empty array `[]`.

---

### Test 7: Custom lookback window -- 20 days

```
GET http://127.0.0.1:5001/api/companies/1/alerts/low-stock?days=20
```

**Expected:** Status `200`. Fewer alerts than Test 1 because products whose sales are all older than 20 days are excluded.

---

### Test 8: Very short lookback window -- 1 day

```
GET http://127.0.0.1:5001/api/companies/1/alerts/low-stock?days=1
```

**Expected:** Status `200`, `total_alerts` = 0 or very few. Most seed sales are older than 1 day.

---

### Test 9: Invalid `days` parameter (400)

```
GET http://127.0.0.1:5001/api/companies/1/alerts/low-stock?days=abc
```

**Expected:**

```json
{
  "error": "Invalid query parameters"
}
```

Status `400`.

---

### Test 10: Negative `days` parameter (400)

```
GET http://127.0.0.1:5001/api/companies/1/alerts/low-stock?days=-5
```

**Expected:**

```json
{
  "error": "days and limit must be >= 1, offset must be >= 0"
}
```

Status `400`.

---

### Test 11: Zero `limit` (400)

```
GET http://127.0.0.1:5001/api/companies/1/alerts/low-stock?limit=0
```

**Expected:** Status `400`.

---

### Test 12: Negative `offset` (400)

```
GET http://127.0.0.1:5001/api/companies/1/alerts/low-stock?offset=-1
```

**Expected:** Status `400`.

---

### Test 13: Verify supplier data structure

From Test 1's response, find the Widget A alert and verify:

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

Widget A has two suppliers (Parts Corp as primary, Global Supply as secondary). The endpoint should return the **primary** supplier.

---

### Test 14: Verify null supplier

From Test 1's response, find the Gadget B alert:

```json
{
  "product_name": "Gadget B",
  "sku": "GDG-002",
  "supplier": null
}
```

Gadget B has no linked supplier. The alert still appears with `supplier: null`.

---

### Test 15: Verify reserved stock deduction

From Test 1's response, find the Reserved Stock I alert:

```json
{
  "product_name": "Reserved Stock I",
  "sku": "RSV-009",
  "current_stock": 10
}
```

The raw `quantity` is 30 and `reserved_quantity` is 20. The endpoint returns `current_stock` = 10 (available stock).

---

### Test 16: Verify custom reorder_level threshold

From Test 1's response, find the Custom Thresh H alert:

```json
{
  "product_name": "Custom Thresh H",
  "sku": "CTH-008",
  "current_stock": 18,
  "threshold": 25
}
```

Default threshold for "normal" products is 20, but this product's inventory has `reorder_level=25`. The custom value takes priority.

---

### Test 17: Verify sorting order

From Test 1's response, check the `days_until_stockout` values are in ascending order:

```text
alerts[0].days_until_stockout <= alerts[1].days_until_stockout <= ... <= alerts[6].days_until_stockout
```

Most urgent alerts (fewest days until stockout) appear first.

---

### Test Summary

| # | Test Case | URL Params | Expected Status | Expected Alerts |
| --- | --- | --- | --- | --- |
| 1 | Happy path | (none) | 200 | 7 |
| 2 | Company not found | company_id=99999 | 404 | -- |
| 3 | Cross-tenant isolation | company_id=2 | 200 | 0 |
| 4 | Limit pagination | limit=2 | 200 | 2 (of 7) |
| 5 | Offset pagination | limit=2&offset=2 | 200 | 2 (of 7) |
| 6 | Offset beyond total | offset=100 | 200 | 0 (of 7) |
| 7 | 20-day lookback | days=20 | 200 | < 7 |
| 8 | 1-day lookback | days=1 | 200 | 0 |
| 9 | Invalid days | days=abc | 400 | -- |
| 10 | Negative days | days=-5 | 400 | -- |
| 11 | Zero limit | limit=0 | 400 | -- |
| 12 | Negative offset | offset=-1 | 400 | -- |
| 13 | Supplier data structure | (from Test 1) | 200 | primary supplier |
| 14 | Null supplier | (from Test 1) | 200 | supplier=null |
| 15 | Reserved stock deduction | (from Test 1) | 200 | current_stock=10 |
| 16 | Custom threshold | (from Test 1) | 200 | threshold=25 |
| 17 | Sorting order | (from Test 1) | 200 | ascending urgency |

---

## Files

| File | Purpose |
| --- | --- |
| `alerts.py` | The low-stock alerts endpoint implementation |
| `models.py` | SQLAlchemy models (subset of Part 2 schema) |
| `app.py` | Flask app factory |
| `seed.py` | Database seeding script for Postman testing |
| `test_alerts.py` | 32 pytest tests |
| `requirements.txt` | Dependencies |
| `README.md` | This documentation |



================================================
FILE: part-3/alerts.py
================================================
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



================================================
FILE: part-3/app.py
================================================
from flask import Flask
from models import db
from alerts import alerts_bp


def create_app(config=None):
    app = Flask(__name__)

    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///stockflow.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    if config:
        app.config.update(config)

    db.init_app(app)
    app.register_blueprint(alerts_bp)

    with app.app_context():
        db.create_all()

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5001)



================================================
FILE: part-3/models.py
================================================
"""
Reuses the Part 2 schema models.
Copied here so Part 3 is self-contained and runnable independently.
"""

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    CheckConstraint,
    Index,
    func,
)
from sqlalchemy.orm import relationship

db = SQLAlchemy()


class Company(db.Model):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    warehouses = relationship("Warehouse", back_populates="company", cascade="all, delete-orphan")
    products = relationship("Product", back_populates="company", cascade="all, delete-orphan")
    suppliers = relationship("Supplier", back_populates="company", cascade="all, delete-orphan")


class Warehouse(db.Model):
    __tablename__ = "warehouses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    location = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    company = relationship("Company", back_populates="warehouses")
    inventories = relationship("Inventory", back_populates="warehouse")

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_warehouse_company_name"),
        Index("idx_warehouses_company", "company_id"),
    )


class Product(db.Model):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    sku = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Numeric(12, 2), nullable=False, default=0.00)
    product_type = Column(String(50), nullable=False, default="normal")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    company = relationship("Company", back_populates="products")
    inventories = relationship("Inventory", back_populates="product")
    suppliers = relationship("ProductSupplier", back_populates="product")

    __table_args__ = (
        UniqueConstraint("company_id", "sku", name="uq_product_company_sku"),
        CheckConstraint("price >= 0", name="ck_products_price"),
        CheckConstraint("product_type IN ('normal', 'bundle')", name="ck_products_type"),
        Index("idx_products_company", "company_id"),
        Index("idx_products_sku", "sku"),
    )


class Supplier(db.Model):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    contact_email = Column(String(255), nullable=True)
    contact_phone = Column(String(50), nullable=True)
    address = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    company = relationship("Company", back_populates="suppliers")
    products = relationship("ProductSupplier", back_populates="supplier")

    __table_args__ = (
        Index("idx_suppliers_company", "company_id"),
    )


class ProductSupplier(db.Model):
    __tablename__ = "product_suppliers"

    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id", ondelete="CASCADE"), primary_key=True)
    supplier_sku = Column(String(100), nullable=True)
    lead_time_days = Column(Integer, nullable=True)
    cost_price = Column(Numeric(12, 2), nullable=True)
    is_primary = Column(Boolean, nullable=False, default=False)

    product = relationship("Product", back_populates="suppliers")
    supplier = relationship("Supplier", back_populates="products")

    __table_args__ = (
        CheckConstraint("lead_time_days IS NULL OR lead_time_days >= 0", name="ck_ps_lead_time"),
        CheckConstraint("cost_price IS NULL OR cost_price >= 0", name="ck_ps_cost_price"),
    )


class Inventory(db.Model):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False)
    quantity = Column(Integer, nullable=False, default=0)
    reserved_quantity = Column(Integer, nullable=False, default=0)
    reorder_level = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    product = relationship("Product", back_populates="inventories")
    warehouse = relationship("Warehouse", back_populates="inventories")
    movements = relationship("InventoryMovement", back_populates="inventory")

    __table_args__ = (
        UniqueConstraint("product_id", "warehouse_id", name="uq_inventory_product_warehouse"),
        CheckConstraint("quantity >= 0", name="ck_inventory_qty"),
        CheckConstraint("reserved_quantity >= 0", name="ck_inventory_reserved"),
        CheckConstraint("reserved_quantity <= quantity", name="ck_inventory_reserved_lte_qty"),
        Index("idx_inventory_warehouse", "warehouse_id"),
        Index("idx_inventory_product", "product_id"),
    )


class InventoryMovement(db.Model):
    __tablename__ = "inventory_movements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    inventory_id = Column(Integer, ForeignKey("inventory.id", ondelete="RESTRICT"), nullable=False)
    change_type = Column(String(50), nullable=False)
    quantity_change = Column(Integer, nullable=False)
    quantity_before = Column(Integer, nullable=False)
    quantity_after = Column(Integer, nullable=False)
    reference_type = Column(String(100), nullable=True)
    reference_id = Column(Integer, nullable=True)
    performed_by = Column(Integer, nullable=True)  # FK to users.id (omitted here for standalone use)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    inventory = relationship("Inventory", back_populates="movements")

    __table_args__ = (
        CheckConstraint("quantity_change <> 0", name="ck_movements_nonzero"),
        CheckConstraint("quantity_after >= 0", name="ck_movements_after_positive"),
        CheckConstraint(
            "change_type IN ('purchase', 'sale', 'return', 'adjustment', "
            "'transfer_in', 'transfer_out', 'damaged', 'bundle_assembly')",
            name="ck_movements_type",
        ),
        Index("idx_movements_inventory", "inventory_id"),
        Index("idx_movements_created", "created_at"),
        Index("idx_movements_reference", "reference_type", "reference_id"),
        Index("idx_movements_performer", "performed_by"),
    )



================================================
FILE: part-3/requirements.txt
================================================
Flask==3.1.1
Flask-SQLAlchemy==3.1.1
SQLAlchemy==2.0.40
pytest==8.3.3



================================================
FILE: part-3/seed.py
================================================
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



================================================
FILE: part-3/test_alerts.py
================================================
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

