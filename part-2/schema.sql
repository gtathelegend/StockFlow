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
