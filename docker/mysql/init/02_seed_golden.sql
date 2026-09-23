-- Hand-authored golden subset for GQ-01..GQ-10 (SPEC §11.3).
-- Fixed reference clock: 2026-09-13T00:00:00Z; business tz Asia/Shanghai.
-- "本周" window: business_date 2026-09-07 .. 2026-09-13 inclusive.

SET NAMES utf8mb4;

INSERT INTO products (product_id, product_name, category, current_stock, reorder_level) VALUES
  ('P001', 'Alpha Widget', 'Electronics', 12, 20),
  ('P002', 'Beta Gadget', 'Electronics', 80, 15),
  ('P003', 'Gamma Tool', 'Tools', 5, 10),
  ('P004', 'Delta Supply', 'Tools', 50, 25);

-- Minimal base-table sample (not used by view; proves tables exist).
INSERT INTO orders (order_id, ordered_at_utc, status) VALUES
  ('O-GOLD-1', '2026-09-13 02:00:00.000000', 'completed');

INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
  ('O-GOLD-1', 'P001', 3, 10.00);

INSERT INTO sales_inventory_daily_fact
  (business_date, product_id, product_name, category, units_sold, gross_sales, current_stock, reorder_level)
VALUES
  -- P001 (AVG units over week = 42/7 = 6.0000)
  ('2026-09-01', 'P001', 'Alpha Widget', 'Electronics', 1, 10.00, 12, 20),
  ('2026-09-07', 'P001', 'Alpha Widget', 'Electronics', 10, 100.00, 12, 20),
  ('2026-09-08', 'P001', 'Alpha Widget', 'Electronics', 8, 80.00, 12, 20),
  ('2026-09-09', 'P001', 'Alpha Widget', 'Electronics', 6, 60.00, 12, 20),
  ('2026-09-10', 'P001', 'Alpha Widget', 'Electronics', 4, 40.00, 12, 20),
  ('2026-09-11', 'P001', 'Alpha Widget', 'Electronics', 2, 20.00, 12, 20),
  ('2026-09-12', 'P001', 'Alpha Widget', 'Electronics', 9, 90.00, 12, 20),
  ('2026-09-13', 'P001', 'Alpha Widget', 'Electronics', 3, 30.00, 12, 20),
  -- P002 week
  ('2026-09-07', 'P002', 'Beta Gadget', 'Electronics', 20, 400.00, 80, 15),
  ('2026-09-08', 'P002', 'Beta Gadget', 'Electronics', 10, 200.00, 80, 15),
  ('2026-09-09', 'P002', 'Beta Gadget', 'Electronics', 15, 300.00, 80, 15),
  ('2026-09-10', 'P002', 'Beta Gadget', 'Electronics', 5, 100.00, 80, 15),
  ('2026-09-11', 'P002', 'Beta Gadget', 'Electronics', 12, 240.00, 80, 15),
  ('2026-09-12', 'P002', 'Beta Gadget', 'Electronics', 8, 160.00, 80, 15),
  ('2026-09-13', 'P002', 'Beta Gadget', 'Electronics', 6, 120.00, 80, 15),
  -- P003 week
  ('2026-09-07', 'P003', 'Gamma Tool', 'Tools', 2, 20.00, 5, 10),
  ('2026-09-08', 'P003', 'Gamma Tool', 'Tools', 2, 20.00, 5, 10),
  ('2026-09-09', 'P003', 'Gamma Tool', 'Tools', 2, 20.00, 5, 10),
  ('2026-09-10', 'P003', 'Gamma Tool', 'Tools', 2, 20.00, 5, 10),
  ('2026-09-11', 'P003', 'Gamma Tool', 'Tools', 2, 20.00, 5, 10),
  ('2026-09-12', 'P003', 'Gamma Tool', 'Tools', 2, 20.00, 5, 10),
  ('2026-09-13', 'P003', 'Gamma Tool', 'Tools', 2, 20.00, 5, 10),
  -- P004 week (Decimal cents)
  ('2026-09-07', 'P004', 'Delta Supply', 'Tools', 1, 5.50, 50, 25),
  ('2026-09-08', 'P004', 'Delta Supply', 'Tools', 1, 5.50, 50, 25),
  ('2026-09-09', 'P004', 'Delta Supply', 'Tools', 1, 5.50, 50, 25),
  ('2026-09-10', 'P004', 'Delta Supply', 'Tools', 1, 5.50, 50, 25),
  ('2026-09-11', 'P004', 'Delta Supply', 'Tools', 1, 5.50, 50, 25),
  ('2026-09-12', 'P004', 'Delta Supply', 'Tools', 1, 5.50, 50, 25),
  ('2026-09-13', 'P004', 'Delta Supply', 'Tools', 1, 5.50, 50, 25);
