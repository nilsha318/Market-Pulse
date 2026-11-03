-- Run this after connecting pgAdmin to the `market_pulse` database.
-- Source numeric/date values are text in sales to preserve the CSV exactly.

CREATE TABLE IF NOT EXISTS sales (
    source_row BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invoice_id TEXT,
    branch TEXT,
    city TEXT,
    customer_type TEXT,
    gender TEXT,
    product_line TEXT,
    unit_price TEXT,
    quantity TEXT,
    tax_5_percent TEXT,
    sales TEXT,
    date TEXT,
    time TEXT,
    payment TEXT,
    cogs TEXT,
    gross_margin_percentage TEXT,
    gross_income TEXT,
    rating TEXT
);

CREATE INDEX IF NOT EXISTS idx_sales_invoice ON sales(invoice_id);
CREATE INDEX IF NOT EXISTS idx_sales_product_line ON sales(product_line);
CREATE INDEX IF NOT EXISTS idx_sales_branch ON sales(branch);

CREATE TABLE IF NOT EXISTS offers (
    offer_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product TEXT NOT NULL,
    category TEXT NOT NULL,
    store TEXT NOT NULL,
    regular_price NUMERIC(12, 2) NOT NULL,
    offer_price NUMERIC(12, 2) NOT NULL,
    valid_from DATE NOT NULL,
    valid_until DATE NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dashboard_users (
    username TEXT PRIMARY KEY,
    role TEXT NOT NULL CHECK (role IN ('admin', 'customer', 'employee')),
    department TEXT,
    job_title TEXT,
    password_salt BYTEA NOT NULL,
    password_hash BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Also upgrade an existing schema created before employee dashboards were added.
ALTER TABLE dashboard_users ADD COLUMN IF NOT EXISTS department TEXT;
ALTER TABLE dashboard_users ADD COLUMN IF NOT EXISTS job_title TEXT;
ALTER TABLE dashboard_users DROP CONSTRAINT IF EXISTS dashboard_users_role_check;
ALTER TABLE dashboard_users ADD CONSTRAINT dashboard_users_role_check
    CHECK (role IN ('admin', 'customer', 'employee'));

CREATE TABLE IF NOT EXISTS customer_order_access (
    username TEXT NOT NULL REFERENCES dashboard_users(username) ON DELETE CASCADE,
    order_id TEXT NOT NULL,
    PRIMARY KEY (username, order_id)
);

CREATE TABLE IF NOT EXISTS cart_items (
    cart_key TEXT NOT NULL,
    offer_id BIGINT NOT NULL REFERENCES offers(offer_id),
    quantity INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 99),
    PRIMARY KEY (cart_key, offer_id)
);

CREATE TABLE IF NOT EXISTS coupons (
    coupon_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    percent_off NUMERIC(5, 2) NOT NULL CHECK (percent_off > 0 AND percent_off <= 100),
    valid_from DATE NOT NULL,
    valid_until DATE NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
