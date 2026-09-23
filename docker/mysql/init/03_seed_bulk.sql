-- Deterministic bulk seed: 100 products × 100 days = 10000 fact rows.
-- Fixed PRNG-style formulas; random seed constant documented in SEED.md (=42).
-- Category BulkCat keeps GQ filters on Electronics/Tools golden-only.

SET NAMES utf8mb4;

INSERT INTO products (product_id, product_name, category, current_stock, reorder_level)
WITH RECURSIVE digs AS (
  SELECT 0 AS n
  UNION ALL
  SELECT n + 1 FROM digs WHERE n < 99
)
SELECT
  CONCAT('B', LPAD(n + 1, 3, '0')),
  CONCAT('Bulk Product ', n + 1),
  'BulkCat',
  100 + n,
  10 + (n % 20)
FROM digs;

INSERT INTO sales_inventory_daily_fact
  (business_date, product_id, product_name, category, units_sold, gross_sales, current_stock, reorder_level)
WITH RECURSIVE
digs AS (
  SELECT 0 AS n
  UNION ALL
  SELECT n + 1 FROM digs WHERE n < 99
),
days AS (
  SELECT DATE('2026-05-01') AS d, 0 AS i
  UNION ALL
  SELECT d + INTERVAL 1 DAY, i + 1 FROM days WHERE i < 99
)
SELECT
  days.d AS business_date,
  CONCAT('B', LPAD(digs.n + 1, 3, '0')) AS product_id,
  CONCAT('Bulk Product ', digs.n + 1) AS product_name,
  'BulkCat' AS category,
  1 + ((digs.n * 17 + days.i * 3 + 42) % 40) AS units_sold,
  CAST(
    (1 + ((digs.n * 17 + days.i * 3 + 42) % 40)) * (5 + (digs.n % 10))
    AS DECIMAL(18, 2)
  ) AS gross_sales,
  100 + digs.n AS current_stock,
  10 + (digs.n % 20) AS reorder_level
FROM digs
CROSS JOIN days;
