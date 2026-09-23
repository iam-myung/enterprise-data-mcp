# Demo MySQL seed contract (SPEC §11.3 / Step 6.1)

## Fixed constants
- **RANDOM_SEED**: `42` (used in bulk units/gross formulas)
- **REFERENCE_CLOCK_UTC**: `2026-09-13T00:00:00Z`
- **BUSINESS_TIMEZONE**: `Asia/Shanghai`
- **Target view rows**: `≥ 10000` (`v_sales_inventory_daily`)
  - Golden fact rows: `29`
  - Bulk fact rows: `100 products × 100 days = 10000`
  - Total: `10029`

## Time rules
- Database session/storage time zone: UTC (`+00:00`).
- `business_date` is a calendar date in `Asia/Shanghai` (DATE column; no time component).
- Demo “本周” relative to reference clock: `2026-09-07` .. `2026-09-13` inclusive.

## Money / null / sort
- `gross_sales`: `DECIMAL(18,2)`; outbound golden expectations use decimal **strings**.
- Empty query result is success with `result_status=EMPTY` (see GQ-09).
- NULL aggregation semantics for GQ-07 use only non-NULL golden week cells (no NULL units in golden week).
- Stable sort for golden queries: explicit `order_by` in `golden_queries.yaml`.

## Objects
| Object | Role |
| --- | --- |
| `products` | Dimension + stock |
| `orders` / `order_items` | Base transactional sample (minimal) |
| `sales_inventory_daily_fact` | Pre-aggregated daily grain |
| `v_sales_inventory_daily` | Authorized read view over the fact table |

## Isolation
- Generated entirely inside `enterprise_data_mcp/`; no external sample SQL.
- Bulk category `BulkCat` keeps Electronics/Tools filters golden-only.

## Init order
1. `01_schema.sql`
2. `02_seed_golden.sql`
3. `03_seed_bulk.sql`
