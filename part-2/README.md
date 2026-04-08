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

## Files

| File | Purpose |
|------|---------|
| `schema.sql` | PostgreSQL DDL -- the complete schema in raw SQL |
| `models.py` | SQLAlchemy ORM models matching the DDL |
| `test_schema.py` | 35 pytest tests for constraints and relationships |
| `requirements.txt` | Python dependencies |
| `README.md` | This documentation |
