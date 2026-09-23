-- SPEC §11.3 demo schema (independent; no CASE SQL).
-- Physical objects: products, orders, order_items, v_sales_inventory_daily

SET NAMES utf8mb4;
SET time_zone = '+00:00';

CREATE TABLE products (
  product_id VARCHAR(32) NOT NULL,
  product_name VARCHAR(128) NOT NULL,
  category VARCHAR(64) NOT NULL,
  current_stock INT NOT NULL,
  reorder_level INT NOT NULL,
  PRIMARY KEY (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE orders (
  order_id VARCHAR(32) NOT NULL,
  ordered_at_utc DATETIME(6) NOT NULL,
  status VARCHAR(32) NOT NULL,
  PRIMARY KEY (order_id),
  KEY idx_orders_ordered_at (ordered_at_utc)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE order_items (
  order_id VARCHAR(32) NOT NULL,
  product_id VARCHAR(32) NOT NULL,
  quantity INT NOT NULL,
  unit_price DECIMAL(18, 2) NOT NULL,
  PRIMARY KEY (order_id, product_id),
  CONSTRAINT fk_order_items_order
    FOREIGN KEY (order_id) REFERENCES orders (order_id),
  CONSTRAINT fk_order_items_product
    FOREIGN KEY (product_id) REFERENCES products (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Pre-aggregated daily grain used by MCP-authorized dataset.
CREATE TABLE sales_inventory_daily_fact (
  business_date DATE NOT NULL,
  product_id VARCHAR(32) NOT NULL,
  product_name VARCHAR(128) NOT NULL,
  category VARCHAR(64) NOT NULL,
  units_sold INT NOT NULL,
  gross_sales DECIMAL(18, 2) NOT NULL,
  current_stock INT NOT NULL,
  reorder_level INT NOT NULL,
  PRIMARY KEY (business_date, product_id),
  KEY idx_fact_category (category),
  KEY idx_fact_product (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE OR REPLACE VIEW v_sales_inventory_daily AS
SELECT
  business_date,
  product_id,
  product_name,
  category,
  units_sold,
  gross_sales,
  current_stock,
  reorder_level
FROM sales_inventory_daily_fact;
