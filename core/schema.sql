-- ============================================================
-- ERP DATABASE — NEW SCHEMA (Purchases / Sales / Tally) — v2
-- PostgreSQL 16+
-- ============================================================

CREATE SCHEMA IF NOT EXISTS public;
SET search_path TO public;

-- ============================================================
-- SHARED / SUPPORT
-- ============================================================

CREATE TABLE IF NOT EXISTS department (
    id   BIGSERIAL PRIMARY KEY,
    name VARCHAR(25) UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS manage_user (
    id            BIGSERIAL PRIMARY KEY,
    user_name     VARCHAR(100) UNIQUE NOT NULL,
    password      TEXT NOT NULL,
    role          VARCHAR(50) NOT NULL DEFAULT 'user',
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_manage_user_username ON manage_user(user_name);

-- ============================================================
-- ITEMS MASTER CATALOG — kept as-is from the old schema.
-- ============================================================

CREATE TABLE IF NOT EXISTS items (
    id            BIGSERIAL PRIMARY KEY,
    name          VARCHAR(255) NOT NULL,
    department    VARCHAR(100),
    hsn           VARCHAR(50),
    unit          VARCHAR(50),
    size          VARCHAR(100),
    defaultMargin NUMERIC(18,2) DEFAULT 0,
    defaultGST    NUMERIC(18,2) DEFAULT 0,
    min_stock     NUMERIC(18,2) DEFAULT 0,
    createdAt     TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_items_name_size ON items(name, size);
CREATE INDEX IF NOT EXISTS idx_items_name_size_ci ON items(LOWER(name), LOWER(COALESCE(size,'')));

CREATE TABLE IF NOT EXISTS app_state (
    id                 INTEGER PRIMARY KEY,
    items_synced_upto  BIGINT DEFAULT 0,
    CONSTRAINT app_state_single_row CHECK (id = 1)
);

INSERT INTO app_state (id, items_synced_upto) VALUES (1, 0) ON CONFLICT (id) DO NOTHING;

-- ============================================================
-- ACCOUNTS & SHOP SETTINGS — out of scope for redesign, kept
-- ============================================================

CREATE TABLE IF NOT EXISTS accounts (
    id             BIGSERIAL PRIMARY KEY,
    name           VARCHAR(255) UNIQUE NOT NULL,
    type           VARCHAR(50) DEFAULT 'cash',
    openingBalance NUMERIC(18,2) DEFAULT 0,
    currentBalance NUMERIC(18,2) DEFAULT 0,
    accountNo      VARCHAR(100),
    ifsc           VARCHAR(50),
    createdAt      TIMESTAMP
);

CREATE TABLE IF NOT EXISTS shop_settings (
    id          INTEGER PRIMARY KEY,
    shop_name   VARCHAR(255) DEFAULT '',
    address     TEXT DEFAULT '',
    phone       VARCHAR(30) DEFAULT '',
    gst_no      VARCHAR(30) DEFAULT '',
    footer_note TEXT DEFAULT '',
    CONSTRAINT shop_settings_single_row CHECK (id = 1)
);

INSERT INTO shop_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS thermal_printer_settings (
    id          INTEGER PRIMARY KEY,
    enabled     SMALLINT DEFAULT 0,
    vendor_id   VARCHAR(10) DEFAULT '',
    product_id  VARCHAR(10) DEFAULT '',
    paper_width INTEGER DEFAULT 80,
    auto_cut    SMALLINT DEFAULT 1,
    CONSTRAINT thermal_printer_settings_single_row CHECK (id = 1)
);

INSERT INTO thermal_printer_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- ============================================================
-- TALLY MODULE
-- ============================================================

CREATE TABLE IF NOT EXISTS account_groups (
    id         BIGSERIAL PRIMARY KEY,
    name       VARCHAR(255) UNIQUE NOT NULL,
    parent_id  BIGINT REFERENCES account_groups(id),
    group_type VARCHAR(50) NOT NULL,
    nature     VARCHAR(20),
    is_primary BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ledgers (
    id              BIGSERIAL PRIMARY KEY,
    name            VARCHAR(255) UNIQUE NOT NULL,
    group_id        BIGINT REFERENCES account_groups(id),
    opening_balance NUMERIC(18,2) DEFAULT 0,
    balance_type    VARCHAR(20) CHECK (balance_type IN ('Debit','Credit')),
    contact_person  VARCHAR(255),
    phone           VARCHAR(30),
    email           VARCHAR(255),
    address         TEXT,
    gst_no          VARCHAR(30),
    pan_no          VARCHAR(20),
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS voucher_types (
    id        BIGSERIAL PRIMARY KEY,
    name      VARCHAR(100) UNIQUE NOT NULL,
    code      VARCHAR(100) UNIQUE NOT NULL,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS vouchers (
    id              BIGSERIAL PRIMARY KEY,
    voucher_number  VARCHAR(100) UNIQUE NOT NULL,
    voucher_type_id BIGINT REFERENCES voucher_types(id),
    date            DATE NOT NULL,
    reference       VARCHAR(255),
    narration       TEXT,
    created_by      VARCHAR(100),
    is_posted       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_vouchers_date ON vouchers(date);
CREATE INDEX IF NOT EXISTS idx_vouchers_type ON vouchers(voucher_type_id);
CREATE INDEX IF NOT EXISTS idx_vouchers_type_number ON vouchers(voucher_type_id, voucher_number);

CREATE TABLE IF NOT EXISTS voucher_entries (
    id         BIGSERIAL PRIMARY KEY,
    voucher_id BIGINT NOT NULL REFERENCES vouchers(id) ON DELETE CASCADE,
    ledger_id  BIGINT NOT NULL REFERENCES ledgers(id),
    debit      NUMERIC(18,2) DEFAULT 0,
    credit     NUMERIC(18,2) DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_voucher_entries_vid ON voucher_entries(voucher_id);
CREATE INDEX IF NOT EXISTS idx_voucher_entries_lid ON voucher_entries(ledger_id);
-- Covering index: trial balance / balance sheet read SUM(debit)+SUM(credit) per ledger.
-- With INCLUDE, PostgreSQL can satisfy the whole aggregate from the index without
-- hitting the main heap (index-only scan), making these reports dramatically faster
-- on large voucher_entries tables.
CREATE INDEX IF NOT EXISTS idx_voucher_entries_lid_cov
    ON voucher_entries(ledger_id, voucher_id)
    INCLUDE (debit, credit);
-- Covering index for voucher_id aggregations (amount per voucher in list/day-book).
CREATE INDEX IF NOT EXISTS idx_voucher_entries_vid_cov
    ON voucher_entries(voucher_id)
    INCLUDE (debit, credit);
-- Composite index to satisfy ORDER BY v.date DESC, v.id DESC without a sort step.
CREATE INDEX IF NOT EXISTS idx_vouchers_date_id ON vouchers(date DESC, id DESC);


-- Ledger & group indexes (used by balance sheet / trial balance bulk joins)
CREATE INDEX IF NOT EXISTS idx_ledgers_group_id   ON ledgers(group_id);
CREATE INDEX IF NOT EXISTS idx_ledgers_is_active  ON ledgers(is_active);
CREATE INDEX IF NOT EXISTS idx_ledgers_name       ON ledgers(name);

CREATE TABLE IF NOT EXISTS stock_items (
    id             BIGSERIAL PRIMARY KEY,
    name           VARCHAR(255) NOT NULL,
    group_id       BIGINT REFERENCES account_groups(id),
    unit           VARCHAR(50),
    opening_stock  NUMERIC(18,2) DEFAULT 0,
    opening_value  NUMERIC(18,2) DEFAULT 0,
    gst_rate       NUMERIC(6,2) DEFAULT 0,
    hsn_code       VARCHAR(50),
    is_active      BOOLEAN DEFAULT TRUE,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS stock_ledger (
    id            BIGSERIAL PRIMARY KEY,
    voucher_id    BIGINT REFERENCES vouchers(id),
    stock_item_id BIGINT REFERENCES stock_items(id),
    quantity_in   NUMERIC(18,2) DEFAULT 0,
    quantity_out  NUMERIC(18,2) DEFAULT 0,
    rate          NUMERIC(18,2) DEFAULT 0,
    amount        NUMERIC(18,2) DEFAULT 0,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- PARTIES
-- ============================================================

CREATE TABLE IF NOT EXISTS parties (
    party_id   BIGSERIAL PRIMARY KEY,
    party_name VARCHAR(255) NOT NULL,
    contact_no VARCHAR(30),
    address    TEXT,
    gst_no     VARCHAR(30) UNIQUE,
    status     VARCHAR(20) DEFAULT 'Cash' CHECK (status IN ('Cash','Credit')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_parties_name ON parties(party_name);
CREATE INDEX IF NOT EXISTS idx_parties_status ON parties(status);
CREATE INDEX IF NOT EXISTS idx_parties_gst ON parties(gst_no);

-- ============================================================
-- PURCHASES HEADER
-- ============================================================

CREATE TABLE IF NOT EXISTS purchases_header (
    id          BIGSERIAL PRIMARY KEY,
    purchase_id BIGINT,
    party_id    BIGINT REFERENCES parties(party_id),
    date        DATE NOT NULL,
    due_date    DATE,
    status      VARCHAR(10) DEFAULT 'Cash' CHECK (status IN ('Cash','Credit','Partial','Paid','Overdue','deleted')),
    invoice_no  VARCHAR(100),
    voucher_id  BIGINT REFERENCES vouchers(id),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_purchases_header_date ON purchases_header(date);
CREATE INDEX IF NOT EXISTS idx_purchases_header_status ON purchases_header(status);
CREATE INDEX IF NOT EXISTS idx_purchases_header_party ON purchases_header(party_id);
CREATE INDEX IF NOT EXISTS idx_purchases_header_invoice ON purchases_header(invoice_no);

-- Migration for databases created before due_date / Overdue / deleted status support was added
ALTER TABLE purchases_header ADD COLUMN IF NOT EXISTS due_date DATE;
ALTER TABLE purchases_header DROP CONSTRAINT IF EXISTS purchases_header_status_check;
ALTER TABLE purchases_header ADD CONSTRAINT purchases_header_status_check
    CHECK (status IN ('Cash','Credit','Partial','Paid','Overdue','deleted'));

-- ============================================================
-- PRODUCTS
-- ============================================================

CREATE TABLE IF NOT EXISTS products (
    product_id       BIGSERIAL PRIMARY KEY,
    party_id         BIGINT REFERENCES parties(party_id),
    purchase_id      BIGINT REFERENCES purchases_header(id),
    item_name        VARCHAR(255) NOT NULL,
    size             TEXT,
    date             DATE,
    total_buy_price  NUMERIC(18,2) DEFAULT 0,
    unit_price       NUMERIC(18,2) NOT NULL,
    department       VARCHAR(100),
    margin           NUMERIC(8,2) DEFAULT 0,
    qty              NUMERIC(18,2) NOT NULL DEFAULT 0,
    sold             NUMERIC(18,2) DEFAULT 0,
    remaining        NUMERIC(18,2) DEFAULT 0,
    projected_margin NUMERIC(18,2) DEFAULT 0,
    status           VARCHAR(10) DEFAULT 'Cash' CHECK (status IN ('Cash','Credit','Partial','Paid','deleted')),
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE products DROP CONSTRAINT IF EXISTS products_status_check;
ALTER TABLE products ADD CONSTRAINT products_status_check
    CHECK (status IN ('Cash','Credit','Partial','Paid','deleted'));

CREATE INDEX IF NOT EXISTS idx_products_name ON products(item_name);
CREATE INDEX IF NOT EXISTS idx_products_department ON products(department);
CREATE INDEX IF NOT EXISTS idx_products_status ON products(status);
CREATE INDEX IF NOT EXISTS idx_products_purchase ON products(purchase_id);
CREATE INDEX IF NOT EXISTS idx_products_name_size_ci ON products(LOWER(item_name), LOWER(COALESCE(size,'')));

-- Partial index for stock_value aggregate (rows that actually contribute)
CREATE INDEX IF NOT EXISTS idx_products_stock_value 
    ON products(product_id, qty, remaining, total_buy_price)
    WHERE remaining > 0 AND product_id IS NOT NULL AND status != 'deleted';

-- ============================================================
-- PURCHASE ITEM (+ sentinel)
-- ============================================================

CREATE TABLE IF NOT EXISTS purchase_item (
    id            BIGSERIAL PRIMARY KEY,
    product_id    BIGINT REFERENCES products(product_id) ON DELETE CASCADE,
    party_id      BIGINT REFERENCES parties(party_id),
    item_name     VARCHAR(255),
    size          VARCHAR(50),
    barcode_no    BIGINT UNIQUE NOT NULL,
    buy_price     NUMERIC(18,2),
    sale_price    NUMERIC(18,2) DEFAULT 0,
    margin        NUMERIC(8,2) DEFAULT 0,
    is_available  VARCHAR(20) DEFAULT 'available' CHECK (is_available IN ('available','sold','deleted')),
    sold_at       TIMESTAMP,
    is_returned   SMALLINT DEFAULT 0,
    last_barcode  BIGINT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE purchase_item DROP CONSTRAINT IF EXISTS purchase_item_is_available_check;
ALTER TABLE purchase_item ADD CONSTRAINT purchase_item_is_available_check
    CHECK (is_available IN ('available','sold','deleted'));


CREATE INDEX IF NOT EXISTS idx_purchase_item_barcode ON purchase_item(barcode_no);
CREATE INDEX IF NOT EXISTS idx_purchase_item_product ON purchase_item(product_id);
CREATE INDEX IF NOT EXISTS idx_purchase_item_availability ON purchase_item(is_available);
CREATE INDEX IF NOT EXISTS idx_purchase_item_returned ON purchase_item(is_returned);

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS idx_purchase_item_name_trgm
    ON purchase_item USING GIN (item_name gin_trgm_ops);

INSERT INTO purchase_item (product_id, party_id, item_name, size, barcode_no, buy_price, last_barcode)
VALUES (NULL, NULL, NULL, NULL, 0, NULL, 9999)
ON CONFLICT (barcode_no) DO NOTHING;

-- ============================================================
-- PURCHASE RETURNS
-- One row per returned line (saved by /api/purchase_return_bill,
-- listed by /api/purchase_returns). Previously return_bill_no/reason
-- were never persisted anywhere, so the return bills list was always
-- missing that data.
-- ============================================================

CREATE TABLE IF NOT EXISTS purchase_return_items (
    id                BIGSERIAL PRIMARY KEY,
    return_bill_no    VARCHAR(100) NOT NULL,
    purchase_item_id  BIGINT REFERENCES purchase_item(id),
    product_id        BIGINT REFERENCES products(product_id),
    party             VARCHAR(255),
    item_name         VARCHAR(255),
    size              VARCHAR(50),
    qty               NUMERIC(18,2) DEFAULT 1,
    buy_price         NUMERIC(18,2) DEFAULT 0,
    buy_total         NUMERIC(18,2) DEFAULT 0,
    reason            TEXT,
    date              DATE,
    invoice_no        VARCHAR(100),
    invoice_date      DATE,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE purchase_return_items ADD COLUMN IF NOT EXISTS invoice_no VARCHAR(100);
ALTER TABLE purchase_return_items ADD COLUMN IF NOT EXISTS invoice_date DATE;

CREATE INDEX IF NOT EXISTS idx_purchase_return_items_bill ON purchase_return_items(return_bill_no);
CREATE INDEX IF NOT EXISTS idx_purchase_return_items_date ON purchase_return_items(date);

-- ============================================================
-- REPLACE / EXCHANGE BILLS
-- ============================================================

CREATE TABLE IF NOT EXISTS replace_bills (
    id             BIGSERIAL PRIMARY KEY,
    replaceBillNo  VARCHAR(100),
    date           DATE,
    customerName   VARCHAR(255),
    customerNo     VARCHAR(50),
    oldTotal       NUMERIC(18,2) DEFAULT 0,
    newTotal       NUMERIC(18,2) DEFAULT 0,
    difference     NUMERIC(18,2) DEFAULT 0,
    discount       NUMERIC(18,2) DEFAULT 0,
    note           TEXT
);

CREATE TABLE IF NOT EXISTS replace_bill_items (
    id                BIGSERIAL PRIMARY KEY,
    replace_bill_id   BIGINT NOT NULL REFERENCES replace_bills(id) ON DELETE CASCADE,
    side              VARCHAR(10) CHECK (side IN ('old','new')),
    item              VARCHAR(255),
    size              VARCHAR(100),
    qty               NUMERIC(18,2) DEFAULT 1,
    sell_price        NUMERIC(18,2) DEFAULT 0,
    sell_total        NUMERIC(18,2) DEFAULT 0,
    barcode_code      VARCHAR(100),
    purchase_item_id  BIGINT REFERENCES purchase_item(id)
);

CREATE INDEX IF NOT EXISTS idx_replace_bill_items_rbid ON replace_bill_items(replace_bill_id);

-- ============================================================
-- PURCHASE PAYMENTS
-- ============================================================

CREATE TABLE IF NOT EXISTS purchase_payments (
    id                         BIGSERIAL PRIMARY KEY,
    purchase_id                BIGINT UNIQUE NOT NULL REFERENCES purchases_header(id),
    party_id                   BIGINT REFERENCES parties(party_id),
    is_credit                  INT DEFAULT 0,
    mode_of_payment            VARCHAR(50),
    total_buy_amount           NUMERIC(18,2) DEFAULT 0,
    total_with_gst             NUMERIC(18,2) DEFAULT 0,
    total_buy_amount_discount  NUMERIC(18,2) DEFAULT 0,
    paid_amount                NUMERIC(18,2) DEFAULT 0,
    remaining_amount           NUMERIC(18,2) DEFAULT 0,
    cgst                       NUMERIC(6,2) DEFAULT 0,
    sgst                       NUMERIC(6,2) DEFAULT 0,
    igst                       NUMERIC(6,2) DEFAULT 0,
    discount                   NUMERIC(18,2) DEFAULT 0,
    status                     VARCHAR(20) DEFAULT 'completed'
);

CREATE INDEX IF NOT EXISTS idx_purchase_payments_party ON purchase_payments(party_id);

-- ============================================================
-- CUSTOMERS
-- ============================================================

CREATE TABLE IF NOT EXISTS customers (
    customer_id   BIGSERIAL PRIMARY KEY,
    customer_name VARCHAR(255) NOT NULL,
    customer_no   VARCHAR(30),
    status        SMALLINT DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(customer_name);
CREATE INDEX IF NOT EXISTS idx_customers_status ON customers(status);

-- ============================================================
-- SALES
-- ============================================================

CREATE TABLE IF NOT EXISTS sales (
    sale_id          BIGSERIAL PRIMARY KEY,
    customers_id     BIGINT REFERENCES customers(customer_id),
    voucher_id       BIGINT REFERENCES vouchers(id),
    status           VARCHAR(10) DEFAULT 'Cash' CHECK (status IN ('Cash','Credit','Partial','Paid')),
    bill_no          VARCHAR(100) UNIQUE,
    date             DATE NOT NULL,
    due_date         DATE,
    total_buy_price  NUMERIC(18,2) DEFAULT 0,
    total_sale_price NUMERIC(18,2) DEFAULT 0,
    total_profit     NUMERIC(18,2) DEFAULT 0,
    discount         NUMERIC(18,2) DEFAULT 0,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(date);
CREATE INDEX IF NOT EXISTS idx_sales_status ON sales(status);
CREATE INDEX IF NOT EXISTS idx_sales_bill_no ON sales(bill_no);
CREATE INDEX IF NOT EXISTS idx_sales_customer ON sales(customers_id);

-- ============================================================
-- SOLD ITEMS
-- ============================================================

CREATE TABLE IF NOT EXISTS sold_items (
    sold_item_id     BIGSERIAL PRIMARY KEY,
    sale_id          BIGINT NOT NULL REFERENCES sales(sale_id) ON DELETE CASCADE,
    product_id       BIGINT,
    item_name        VARCHAR(255) NOT NULL,
    size             TEXT,
    quantity         NUMERIC(18,2) NOT NULL,
    unit_buy_price   NUMERIC(18,2) DEFAULT 0,
    margin           NUMERIC(8,2) DEFAULT 0,
    unit_sale_price  NUMERIC(18,2) DEFAULT 0,
    total_buy_price  NUMERIC(18,2) DEFAULT 0,
    total_sale_price NUMERIC(18,2) DEFAULT 0,
    status           SMALLINT DEFAULT 0,
    is_return        SMALLINT DEFAULT 0,
    return_qty       NUMERIC(18,2) DEFAULT 0,
    is_old           SMALLINT DEFAULT 0,
    actual_price     NUMERIC(18,2) DEFAULT 0,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sold_items_sale ON sold_items(sale_id);
CREATE INDEX IF NOT EXISTS idx_sold_items_product ON sold_items(product_id);
CREATE INDEX IF NOT EXISTS idx_sold_items_item_name ON sold_items(item_name);

-- ============================================================
-- SOLD ITEM BARCODES
-- ============================================================

CREATE TABLE IF NOT EXISTS sold_item_barcodes (
    id            BIGSERIAL PRIMARY KEY,
    sold_item_id  BIGINT NOT NULL REFERENCES sold_items(sold_item_id) ON DELETE CASCADE,
    barcode_no    BIGINT NOT NULL REFERENCES purchase_item(barcode_no)
);

CREATE INDEX IF NOT EXISTS idx_sold_item_barcodes_sold_item ON sold_item_barcodes(sold_item_id);
CREATE INDEX IF NOT EXISTS idx_sold_item_barcodes_barcode ON sold_item_barcodes(barcode_no);

-- ============================================================
-- SALES RETURNS
-- One row per returned line (saved by /api/sales_return_bill, listed
-- by /api/sales_returns). Previously return_bill_no/reason were never
-- persisted anywhere, so the return bills list was always missing
-- that data.
-- ============================================================

CREATE TABLE IF NOT EXISTS sales_return_items (
    id             BIGSERIAL PRIMARY KEY,
    return_bill_no VARCHAR(100) NOT NULL,
    sold_item_id   BIGINT REFERENCES sold_items(sold_item_id),
    customer_name  VARCHAR(255),
    customer_no    VARCHAR(50),
    item_name      VARCHAR(255),
    size           VARCHAR(50),
    qty            NUMERIC(18,2) DEFAULT 1,
    sell_price     NUMERIC(18,2) DEFAULT 0,
    sell_total     NUMERIC(18,2) DEFAULT 0,
    reason         TEXT,
    date           DATE,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sales_return_items_bill ON sales_return_items(return_bill_no);
CREATE INDEX IF NOT EXISTS idx_sales_return_items_date ON sales_return_items(date);

-- ============================================================
-- SALES PAYMENTS
-- ============================================================

CREATE TABLE IF NOT EXISTS sales_payments (
    id                     BIGSERIAL PRIMARY KEY,
    sale_id                BIGINT UNIQUE NOT NULL REFERENCES sales(sale_id),
    bill_no                VARCHAR(100) UNIQUE,
    mode_of_payment        VARCHAR(50),
    cash                   NUMERIC(18,2) DEFAULT 0,
    online                 NUMERIC(18,2) DEFAULT 0,
    discount               NUMERIC(18,2) DEFAULT 0,
    total_amount           NUMERIC(18,2) DEFAULT 0,
    paid_amount            NUMERIC(18,2) DEFAULT 0,
    remaining_amount       NUMERIC(18,2) DEFAULT 0,
    final_amount_discount  NUMERIC(18,2) DEFAULT 0
);

-- ============================================================
-- DEFAULT SEED DATA
-- ============================================================

INSERT INTO account_groups (name, parent_id, group_type, nature, is_primary)
VALUES
('Capital Account',NULL,'Equity','Credit',TRUE),
('Current Assets',NULL,'Assets','Debit',TRUE),
('Current Liabilities',NULL,'Liabilities','Credit',TRUE),
('Direct Income',NULL,'Income','Credit',TRUE),
('Direct Expenses',NULL,'Expense','Debit',TRUE),
('Indirect Income',NULL,'Income','Credit',TRUE),
('Indirect Expenses',NULL,'Expense','Debit',TRUE),
('Fixed Assets',NULL,'Assets','Debit',TRUE),
('Bank Accounts',NULL,'Assets','Debit',FALSE),
('Cash-in-Hand',NULL,'Assets','Debit',FALSE),
('Sundry Debtors',NULL,'Assets','Debit',FALSE),
('Sundry Creditors',NULL,'Liabilities','Credit',FALSE),
('Duties & Taxes',NULL,'Liabilities','Credit',FALSE),
('Sales Accounts',NULL,'Income','Credit',FALSE),
('Purchase Accounts',NULL,'Expense','Debit',FALSE),
('Stock-in-Hand',NULL,'Assets','Debit',FALSE),
('Reserves & Surplus',NULL,'Equity','Credit',TRUE)
ON CONFLICT (name) DO NOTHING;

INSERT INTO voucher_types (name, code)
VALUES
('Payment','PAYMENT'), ('Receipt','RECEIPT'), ('Contra','CONTRA'), ('Journal','JOURNAL'),
('Purchase','PURCHASE'), ('Sales','SALES'), ('Sales Return','SALESRET'),
('Purchase Return','PURCHASERET'), ('Credit Note','CREDITNOTE'), ('Debit Note','DEBITNOTE')
ON CONFLICT (code) DO NOTHING;

INSERT INTO ledgers (name, group_id, opening_balance, balance_type)
VALUES
('Cash', (SELECT id FROM account_groups WHERE name='Cash-in-Hand'), 0, 'Debit'),
('Bank Account', (SELECT id FROM account_groups WHERE name='Bank Accounts'), 0, 'Debit'),
('Capital', (SELECT id FROM account_groups WHERE name='Capital Account'), 0, 'Credit'),
('Sales', (SELECT id FROM account_groups WHERE name='Sales Accounts'), 0, 'Credit'),
('Purchase', (SELECT id FROM account_groups WHERE name='Purchase Accounts'), 0, 'Debit'),
('GST Payable', (SELECT id FROM account_groups WHERE name='Duties & Taxes'), 0, 'Credit'),
('GST Input', (SELECT id FROM account_groups WHERE name='Duties & Taxes'), 0, 'Debit'),
('Discount Allowed', (SELECT id FROM account_groups WHERE name='Indirect Expenses'), 0, 'Debit'),
('Discount Received', (SELECT id FROM account_groups WHERE name='Indirect Income'), 0, 'Credit')
ON CONFLICT (name) DO UPDATE SET group_id = EXCLUDED.group_id WHERE ledgers.group_id IS NULL;

INSERT INTO department (name) VALUES ('General') ON CONFLICT (name) DO NOTHING;

INSERT INTO accounts (name, type, openingBalance, currentBalance, createdAt)
VALUES
('Cash', 'cash', 0, 0, CURRENT_TIMESTAMP),
('Bank', 'bank', 0, 0, CURRENT_TIMESTAMP)
ON CONFLICT (name) DO NOTHING;

-- ============================================================
-- DASHBOARD CACHE TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS dashboard_data (
    period                 VARCHAR(20) PRIMARY KEY,
    period_start           DATE,
    period_end             DATE,
    period_sales           NUMERIC(18,2) DEFAULT 0,
    period_purchases       NUMERIC(18,2) DEFAULT 0,
    period_profit          NUMERIC(18,2) DEFAULT 0,
    cash_sales             NUMERIC(18,2) DEFAULT 0,
    credit_sales           NUMERIC(18,2) DEFAULT 0,
    credit_purchases       NUMERIC(18,2) DEFAULT 0,
    purchase_count         INTEGER DEFAULT 0,
    sales_count            INTEGER DEFAULT 0,
    recent_purchases_json  TEXT,
    recent_sales_json      TEXT,
    payment_mode_json      TEXT,
    stock_summary_json     TEXT,
    low_stock_alerts_json  TEXT,
    top_products_json      TEXT,
    recent_activities_json TEXT,
    total_receivable       NUMERIC(18,2) DEFAULT 0,
    total_payable          NUMERIC(18,2) DEFAULT 0,
    stock_qty              NUMERIC(18,2) DEFAULT 0,
    stock_value            NUMERIC(18,2) DEFAULT 0,
    sales_vs_purchase_json TEXT,
    monthly_profit_json    TEXT,
    last_updated           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    snapshot_updated_at    TIMESTAMP
);

ALTER TABLE dashboard_data ADD COLUMN IF NOT EXISTS purchase_count INTEGER DEFAULT 0;
ALTER TABLE dashboard_data ADD COLUMN IF NOT EXISTS sales_count INTEGER DEFAULT 0;
ALTER TABLE dashboard_data ADD COLUMN IF NOT EXISTS recent_purchases_json TEXT;
ALTER TABLE dashboard_data ADD COLUMN IF NOT EXISTS recent_sales_json TEXT;
ALTER TABLE dashboard_data ADD COLUMN IF NOT EXISTS payment_mode_json TEXT;
ALTER TABLE dashboard_data ADD COLUMN IF NOT EXISTS stock_summary_json TEXT;
ALTER TABLE dashboard_data ADD COLUMN IF NOT EXISTS low_stock_alerts_json TEXT;
ALTER TABLE dashboard_data ADD COLUMN IF NOT EXISTS top_products_json TEXT;
ALTER TABLE dashboard_data ADD COLUMN IF NOT EXISTS recent_activities_json TEXT;
ALTER TABLE dashboard_data DROP COLUMN IF EXISTS financial_summary_json;
ALTER TABLE dashboard_data ADD COLUMN IF NOT EXISTS total_receivable NUMERIC(18,2) DEFAULT 0;
ALTER TABLE dashboard_data ADD COLUMN IF NOT EXISTS total_payable NUMERIC(18,2) DEFAULT 0;
ALTER TABLE dashboard_data ADD COLUMN IF NOT EXISTS stock_qty NUMERIC(18,2) DEFAULT 0;
ALTER TABLE dashboard_data ADD COLUMN IF NOT EXISTS stock_value NUMERIC(18,2) DEFAULT 0;
ALTER TABLE dashboard_data ADD COLUMN IF NOT EXISTS sales_vs_purchase_json TEXT;
ALTER TABLE dashboard_data ADD COLUMN IF NOT EXISTS monthly_profit_json TEXT;

INSERT INTO dashboard_data (period) VALUES
('today'), ('week'), ('month'), ('lastmonth'), ('alltime')
ON CONFLICT (period) DO NOTHING;

-- ============================================================
-- REPORTS STATS CACHE
-- Real-time cache for Reports > Purchase & Sales analyze-initial stats
-- (see core/reports_cache.py). One row per mode filter.
-- ============================================================

CREATE TABLE IF NOT EXISTS reports_stats_cache (
    mode                 VARCHAR(10) PRIMARY KEY,
    purchase_count       BIGINT DEFAULT 0,
    purchase_qty         NUMERIC(18,2) DEFAULT 0,
    purchase_buy_total   NUMERIC(18,2) DEFAULT 0,
    purchase_sell_total  NUMERIC(18,2) DEFAULT 0,
    purchase_profit      NUMERIC(18,2) DEFAULT 0,
    sale_count           BIGINT DEFAULT 0,
    sale_qty              NUMERIC(18,2) DEFAULT 0,
    sale_cost_total       NUMERIC(18,2) DEFAULT 0,
    sale_sell_total       NUMERIC(18,2) DEFAULT 0,
    sale_profit           NUMERIC(18,2) DEFAULT 0,
    last_updated          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO reports_stats_cache (mode) VALUES
('all'), ('cash'), ('credit')
ON CONFLICT (mode) DO NOTHING;

CREATE TABLE IF NOT EXISTS monthly_stats_cache (
    year         INTEGER NOT NULL,
    month        INTEGER NOT NULL,
    purchases    NUMERIC(18,2) DEFAULT 0,
    sales        NUMERIC(18,2) DEFAULT 0,
    profit       NUMERIC(18,2) DEFAULT 0,
    items_sold   NUMERIC(18,2) DEFAULT 0,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (year, month)
);

CREATE TABLE IF NOT EXISTS daily_profit_cache (
    sale_date    DATE PRIMARY KEY,
    item_count   BIGINT DEFAULT 0,
    qty_sold     NUMERIC(18,2) DEFAULT 0,
    buy_total    NUMERIC(18,2) DEFAULT 0,
    sell_total   NUMERIC(18,2) DEFAULT 0,
    profit       NUMERIC(18,2) DEFAULT 0,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS old_data (
    uniqee_id     BIGINT UNIQUE,
    id            BIGSERIAL PRIMARY KEY,
    item_code     TEXT NOT NULL,
    size          TEXT DEFAULT '',
    buy_mrp       NUMERIC(18,2) DEFAULT 0,
    sell_mrp      NUMERIC(18,2) DEFAULT 0,
    remaining     NUMERIC(18,2) DEFAULT 0,
    sold          NUMERIC(18,2) DEFAULT 0,
    barcode       BIGINT,
    imported_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_return     SMALLINT DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_old_data_uniqee_id ON old_data(uniqee_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_old_data_barcode ON old_data(barcode) WHERE barcode IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_old_data_item_code ON old_data(LOWER(item_code));
CREATE INDEX IF NOT EXISTS idx_old_data_item_code_trim ON old_data(LOWER(TRIM(item_code)));
CREATE INDEX IF NOT EXISTS idx_purchase_item_barcode ON purchase_item(barcode_no);

ANALYZE;
