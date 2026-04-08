# StockFlow: Complete Inventory Management System

A comprehensive database design and API implementation for a multi-company, multi-warehouse inventory management platform.

**Covers:** Code review & debugging, database schema design, and production-ready API implementation with full test suites.

---

## Table of Contents

1. [Part 1: Code Review & Debugging](#part-1-code-review--debugging)
2. [Part 2: Database Design](#part-2-database-design)
3. [Part 3: API Implementation](#part-3-api-implementation)
4. [Quick Start](#quick-start)
5. [Architecture Overview](#architecture-overview)

---

## Part 1: Code Review & Debugging

### Overview

A previous intern wrote a simple product creation endpoint. The code compiles but has critical bugs that would cause issues in production.

**Location:** `part-1/`

### The Original Problem

```python
@app.route('/api/products', methods=['POST'])
def create_product():
    data = request.json
    product = Product(
        name=data['name'],
        sku=data['sku'],
        price=data['price'],
        warehouse_id=data['warehouse_id']  # ← WRONG: products shouldn't have warehouse_id
    )
    db.session.add(product)
    db.session.commit()

    inventory = Inventory(
        product_id=product.id,
        warehouse_id=data['warehouse_id'],
        quantity=data['initial_quantity']
    )
    db.session.add(inventory)
    db.session.commit()  # ← TWO separate commits = data inconsistency risk

    return {"message": "Product created", "product_id": product.id}
```

### Critical Issues Found (14 total)

| # | Issue | Severity | Impact |
|---|-------|----------|--------|
| A | `request.json` not validated | Critical | Crashes on malformed input, 500 error instead of 400 |
| B | Required fields assumed to exist | Critical | Missing fields cause `KeyError`, unhandled 500 |
| C | SKU uniqueness not checked | High | Duplicate SKUs created, breaking search/tracking |
| D | Float instead of Decimal for price | Medium | Rounding errors in financial calculations |
| E | `warehouse_id` on Product model | Critical | Wrong schema -- products tied to one warehouse, can't support multi-warehouse |
| F | Two separate commits | Critical | Product committed, inventory fails → inconsistent state |
| G | No transaction rollback | High | Session in broken state, partial writes not cleaned up |
| H | `initial_quantity` treated as mandatory | Low | Fails when warehouse setup should be optional |
| I | No business-rule validation | Low | Invalid inventory (negative qty, bad warehouse) created |
| J | No proper HTTP status codes | Medium | Clients can't distinguish success from failure |
| K | No authentication/authorization | High | Unauthenticated users can create products |
| L | No idempotency protection | Medium | Retry storms create duplicate products |
| M | No consistent error response format | Low | Clients can't parse errors programmatically |
| N | `warehouse_id` not validated against DB | High | Cryptic FK error instead of helpful "warehouse not found" |

### The Corrected Implementation

**Key improvements:**

✅ Input validation before database operations  
✅ SKU uniqueness check with proper error response  
✅ Warehouse existence validation (404 if not found)  
✅ Single atomic transaction with rollback  
✅ Decimal(12,2) for price (exact currency values)  
✅ `reserved_quantity` support  
✅ Explicit HTTP status codes (201 on success, 400/404/409 on error)  
✅ Consistent JSON error responses  
✅ Optional warehouse/inventory creation  

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

```
48 tests passing
✓ Validation tests (required fields, price types, quantity types)
✓ Route tests (201/400/404/409 status codes)
✓ Transaction atomicity (rollback on error)
✓ Data type handling (Decimal precision)
✓ Multi-warehouse support
✓ Data model correctness
```

### API Test Cases

All requests are `POST http://localhost:5000/api/products`.

**Success cases:**
- Test 1: Create with inventory → 201
- Test 2: Create without inventory → 201
- Test 3: Integer price accepted → 201
- Test 4: Zero initial quantity → 201

**Validation errors (400):**
- Test 6: Missing required fields
- Test 7: Empty body
- Test 8: Invalid JSON
- Test 9: Negative price
- Test 10: Zero price
- Test 11: Non-numeric price

**Conflict (409):**
- Test 5: Duplicate SKU

**Not found (404):**
- Test 12: Nonexistent warehouse

See `part-1/README.md` for all 18 test cases.

---

## Part 2: Database Design

### Overview

Design a database schema for a multi-company, multi-warehouse inventory management system with the following requirements:

- Companies can have multiple warehouses
- Products can be stored in multiple warehouses with different quantities
- Track when inventory levels change (audit trail)
- Suppliers provide products to companies
- Some products might be "bundles" containing other products

**Location:** `part-2/`

### Schema Overview (10 tables)

```
companies ──1:N──> users
    │
    ├──1:N──> warehouses
    │              │
    ├──1:N──> products ──M:N──> suppliers
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

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **No `warehouse_id` on Product** | Products link to warehouses through inventory table. One product can be in many warehouses independently. |
| **SKU unique per company** | Multi-tenant scoping: different companies can use the same SKU independently. `UNIQUE (company_id, sku)` |
| **`ON DELETE RESTRICT` on inventory/movements** | Prevents accidental deletion of audit history. Force app to explicitly handle decommissioning. |
| **`DECIMAL(12,2)` for price** | Avoids floating-point rounding errors in financial calculations |
| **`inventory_movements` audit log** | Immutable record of every stock change with who/what/when/why |
| **Bundle self-reference guard** | `CHECK (bundle_product_id <> component_product_id)` blocks self-references |
| **Warehouse transfers table** | Links `transfer_in` and `transfer_out` movements atomically |
| **`is_active` flags** | Soft delete for products, warehouses, suppliers, users |
| **`reorder_level` per warehouse** | Allows customization of low-stock thresholds per location |

### Critical Improvements Over Original Proposal

**Original solution issues fixed:**

1. **SKU uniqueness scope** — Changed from global to per-company (multi-tenant)
2. **Suppliers not scoped** — Added `company_id` to suppliers table
3. **Bundle nesting unconstrained** — Added self-reference check
4. **Magic strings unchecked** — Added `CHECK` constraints on `product_type`, `change_type`, `status`, `role`
5. **ON DELETE CASCADE on audit** — Changed to `RESTRICT` to prevent history loss
6. **No user tracking** — Added `users` table and `performed_by` on movements
7. **Missing first-class transfers** — Added `warehouse_transfers` table
8. **No transaction history** — Added `quantity_before`/`quantity_after` on movements

### Files

| File | Purpose |
|------|---------|
| `schema.sql` | PostgreSQL DDL (10 tables, constraints, indexes) |
| `models.py` | SQLAlchemy ORM models |
| `test_schema.py` | 35 pytest tests for constraints/relationships |
| `requirements.txt` | Dependencies |
| `README.md` | Full schema documentation with gaps/questions |

### Test Results

```
35 tests passing
✓ Multi-tenancy (SKU scoping, cross-company isolation)
✓ Foreign key constraints (ON DELETE RESTRICT/CASCADE)
✓ Uniqueness constraints (warehouse names, product SKUs)
✓ Check constraints (prices >= 0, quantities valid)
✓ Relationships (1:N, M:N, self-referencing)
✓ Bundle composition (no self-reference)
✓ Inventory lifecycle (reserve, movements)
✓ Data integrity across tables
```

### Test Cases

All tests are Python shell or pytest. See `part-2/README.md` for 11 manual verification scenarios:

- Test 1: Create company and verify relationships
- Test 2: Warehouse names unique per company
- Test 3: Cross-company warehouse isolation
- Test 4: SKU uniqueness per company, not global
- Test 5: Product in multiple warehouses
- Test 6: Cannot delete product with inventory (RESTRICT)
- Test 7: Bundle cannot reference itself
- Test 8: Inventory movement audit trail
- Test 9: Cannot delete inventory with movements (RESTRICT)
- Test 10: Transfer cannot have same source/dest
- Test 11: Product has no warehouse_id column

---

## Part 3: API Implementation

### Overview

Implement a low-stock alerts endpoint that identifies products running low on inventory and suggests reordering.

```
GET /api/companies/{company_id}/alerts/low-stock
```

**Location:** `part-3/`

### Business Rules

- Low stock threshold varies by product type
- Only alert for products with recent sales activity
- Must handle multiple warehouses per company
- Include supplier information for reordering
- Threshold priority: per-warehouse `reorder_level` > product-type default > global fallback

### Critical Issues in Original Solution

| Problem | Original | Fixed |
|---------|----------|-------|
| **N+1 query problem** | 2 queries per row in loop | 3 total queries via subqueries |
| **Wrong tables** | `Sale`/`SaleItem` (don't exist) | `inventory_movements` with `change_type='sale'` |
| **Reserved stock ignored** | Compared raw `quantity` | Uses `quantity - reserved_quantity` |
| **`reorder_level` ignored** | Hardcoded thresholds only | Per-warehouse level > product-type > fallback |
| **`is_active` ignored** | Shows discontinued products | Filters inactive products + warehouses |
| **No company check** | Empty 200 for bad ID | 404 for nonexistent company |
| **No sorting** | Arbitrary order | Sorted by urgency (days until stockout) |
| **No pagination** | All alerts at once | `limit`/`offset` with `total_alerts` |

### Architecture

The endpoint executes **3 queries total** (regardless of data volume, no N+1):

```
1. Sales subquery
   └─> SUM(quantity_change) per inventory_id
       WHERE change_type='sale' AND created_at >= cutoff
       
2. Main query (INNER JOIN sales)
   └─> inventory + product + warehouse + company
       Excludes products with zero recent sales
       
3. Supplier subquery (LEFT JOIN)
   └─> ROW_NUMBER() per product_id
       ORDER BY is_primary DESC, id ASC
       Picks primary supplier, fallback to any active
```

### Available Stock Calculation

```python
available_stock = quantity - reserved_quantity

if available_stock < threshold:
    days_until_stockout = available_stock / (total_sold / lookback_days)
```

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

### Query Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `days` | 30 | Lookback window for "recent" sales |
| `limit` | 50 | Max alerts per response |
| `offset` | 0 | Pagination offset |

### Threshold Priority

```
1. inventory.reorder_level (per product-warehouse, warehouse manager customizable)
2. DEFAULT_THRESHOLDS[product_type] (per type: normal=20, bundle=15)
3. 20 (global fallback)
```

### Edge Cases Handled (16 total)

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
| 14 | Zero average sales rate | days_until_stockout = null |
| 15 | Same product multiple warehouses | Separate alert per warehouse |
| 16 | Large result sets | Paginated via limit/offset |

### Files

| File | Purpose |
|------|---------|
| `alerts.py` | Endpoint implementation (single-query architecture) |
| `models.py` | SQLAlchemy models (subset of Part 2) |
| `app.py` | Flask app factory |
| `seed.py` | Database seeding with realistic test data |
| `test_alerts.py` | 32 pytest tests (comprehensive coverage) |
| `requirements.txt` | Dependencies |
| `README.md` | Full implementation details |

### Test Results

```
32 tests passing
✓ Happy path (7 alerts with correct structure)
✓ Threshold logic (reorder_level override, product-type defaults)
✓ Filtering (no sales, old sales, inactive, cross-tenant)
✓ Reserved stock (deduction from available)
✓ Stockout estimation (correct day calculation)
✓ Supplier info (primary, null, fallback)
✓ Multi-warehouse (per-warehouse alerts)
✓ Sorting (urgency order)
✓ Pagination (limit, offset)
✓ Custom lookback window (days parameter)
✓ Error handling (404 company, 400 invalid params)
```

### Seed Data

The `seed.py` script creates realistic test data:

**Company 1 (Acme Corp):**
- 3 warehouses (2 active, 1 inactive)
- 10 products (various states)
- 2 suppliers
- 11 inventory records with movements

**Company 2 (Other Corp):**
- 1 warehouse
- 1 product (for cross-tenant isolation testing)

**Expected alerts for Company 1:** 7 total

| Product | Stock | Threshold | Reason |
|---------|-------|-----------|--------|
| Widget A | 5 | 20 | Low stock, recent sales |
| Gadget B | 3 | 20 | Low stock, no supplier |
| Multi-WH G | 8 | 20 | Low in east warehouse |
| Multi-WH G | 4 | 20 | Low in west warehouse |
| Bundle F | 10 | 15 | Bundle product type |
| Custom Thresh H | 18 | 25 | Custom reorder_level |
| Reserved Stock I | 10 | 20 | Available = 30 - 20 |

**Filtered out (6 products):**
- Bolt C (stock=100, above threshold)
- Stale Item D (no recent sales)
- Discontinued E (is_active=False)
- Widget A in Closed WH (warehouse is_active=False)
- Other Corp product (different company)

### API Test Cases

All requests are `GET http://127.0.0.1:5001/api/companies/{id}/alerts/low-stock`.

**Success cases:**
- Test 1: Happy path → 200, 7 alerts
- Test 4-6: Pagination (limit, offset)
- Test 7-8: Custom lookback window (days)
- Test 13-17: Data verification (supplier, reserved stock, threshold, sorting)

**Error cases:**
- Test 2: Company not found → 404
- Test 9-12: Invalid parameters → 400

**Isolation:**
- Test 3: Cross-tenant (Other Corp) → 0 alerts

See `part-3/README.md` for all 17 test cases.

---

## Quick Start

### Part 1: Endpoint & Validation

```bash
cd part-1
pip install -r requirements.txt

# Run unit tests
python -m pytest test_validators.py test_routes.py -v

# Start server
python app.py
# Runs on http://127.0.0.1:5000
```

### Part 2: Schema Design

```bash
cd part-2
pip install -r requirements.txt

# Run schema tests
python -m pytest test_schema.py -v

# Or verify manually in Python shell
python
>>> from flask import Flask
>>> from models import db, Company
>>> # ... see README.md for 11 test scenarios
```

### Part 3: Low-Stock Alerts API

```bash
cd part-3
pip install -r requirements.txt

# Seed database
python seed.py

# Start server
python app.py
# Runs on http://127.0.0.1:5001

# Run tests
python -m pytest test_alerts.py -v
```

### Postman Testing

**Part 1:**
```
POST http://127.0.0.1:5000/api/products
Content-Type: application/json

{
  "name": "Wireless Mouse",
  "sku": "WM-001",
  "price": 29.99,
  "warehouse_id": 1,
  "initial_quantity": 100
}
```

**Part 3:**
```
GET http://127.0.0.1:5001/api/companies/1/alerts/low-stock?days=30&limit=50&offset=0
```

---

## Architecture Overview

### Data Flow

```
User Request
    ↓
[API Layer - Validation]
    ├─ Input validation (type, range, existence)
    ├─ Authentication (Part 1: implicit, Part 3: via company_id)
    └─ Authorization (company scoping)
    ↓
[Query Layer - Optimized SQL]
    ├─ Subqueries for aggregates (sales, suppliers)
    ├─ Joins for relationships
    └─ Filters for data isolation
    ↓
[Database - Constraints]
    ├─ Foreign keys (referential integrity)
    ├─ Unique constraints (no duplicates)
    ├─ Check constraints (value validation)
    └─ Indexes (query performance)
    ↓
[Response Layer]
    ├─ Proper HTTP status codes
    ├─ Consistent JSON format
    └─ Pagination metadata
    ↓
Client Response
```

### Key Principles

1. **Data Integrity First** — Constraints at database level, not just application
2. **Auditability** — Every change tracked with who/what/when/why
3. **Multi-Tenancy** — Strict company scoping to prevent data leaks
4. **Performance** — Subqueries instead of N+1, proper indexing
5. **Consistency** — Atomic transactions with rollback on error
6. **Usability** — Clear error messages, proper HTTP status codes
7. **Flexibility** — Configurable thresholds per warehouse, product type, and global

### Technology Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Framework | Flask | 3.1.1 |
| ORM | SQLAlchemy | 2.0.40 |
| Database | SQLite (dev), PostgreSQL (prod) | Latest |
| Testing | pytest | 8.3.3 |
| Language | Python | 3.11+ |

---

## Summary

### Part 1: Code Review & Debugging
- **Goal:** Identify and fix 14 production bugs in a simple product creation endpoint
- **Output:** Corrected implementation with 48 passing tests
- **Key Learnings:** Input validation, transaction management, HTTP status codes

### Part 2: Database Design
- **Goal:** Design a schema for multi-company, multi-warehouse inventory management
- **Output:** 10-table normalized schema with 35 passing tests
- **Key Learnings:** Multi-tenancy design, audit trails, constraint patterns

### Part 3: API Implementation
- **Goal:** Build a low-stock alerts endpoint with optimal query performance
- **Output:** Single-query architecture with 32 passing tests, seed data, and Postman cases
- **Key Learnings:** Query optimization, pagination, data filtering, edge cases

### Combined Test Coverage

- **Unit tests:** 23 (validators) + 35 (schema) + 32 (alerts) = **90 tests**
- **Integration tests:** 25 (routes) = **25 tests**
- **Total:** **115 tests, all passing**

### Code Quality Metrics

| Metric | Target | Achieved |
|--------|--------|----------|
| Test coverage | >80% | ✓ |
| Error handling | Comprehensive | ✓ |
| Documentation | Inline + README | ✓ |
| Code organization | Clear separation | ✓ |
| Performance | No N+1 queries | ✓ |
| Security | Input validation, multi-tenant | ✓ |

---

## Further Reading

- **Part 1:** [part-1/README.md](part-1/README.md) — Detailed analysis of all 14 bugs
- **Part 2:** [part-2/README.md](part-2/README.md) — Schema design decisions and gaps/questions
- **Part 3:** [part-3/README.md](part-3/README.md) — API implementation and edge cases

---

## License

Open source for educational purposes.
