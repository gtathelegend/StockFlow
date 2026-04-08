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

## Files

| File | Purpose |
|------|---------|
| `alerts.py` | The low-stock alerts endpoint implementation |
| `models.py` | SQLAlchemy models (subset of Part 2 schema) |
| `app.py` | Flask app factory |
| `test_alerts.py` | 32 pytest tests |
| `requirements.txt` | Dependencies |
| `README.md` | This documentation |
