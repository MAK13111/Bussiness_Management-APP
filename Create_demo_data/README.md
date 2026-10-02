# Massive Demo Data Generator (500k+ Rows / 20 GB Footprint)

This tool populates the ERP PostgreSQL database with massive, production-grade synthetic demo data:
- **Resumable Execution**: If interrupted (Ctrl+C) or cancelled, the script detects already completed rows and resumes precisely where it left off without starting over.
- **At least 500,000 (5 lac) rows per table** across 20+ relational tables (**10.5+ million rows total**).
- **Target database footprint of 20 GB+**, dynamically calculated and distributed via realistic transaction narrations, billing metadata, and business audit payloads.
- **Ultra-high throughput streaming** via PostgreSQL `COPY FROM STDIN` (~100,000+ rows/second).
- **100% Relational Integrity**: strict foreign-key linkage between Parties, Customers, Items, Purchases, Products, Barcodes, Sales, Returns, Exchanges, Vouchers, and Double-entry Voucher Entries.
- **Automatic Sequence Synchronization**: resynchronizes all `BIGSERIAL` sequences with `setval` so future application transactions (`INSERT`) continue without ID collisions.

---

## 📁 File Structure

Inside `Create_demo_data/`:
- `generate_demo_data.py`: Main executable CLI script with live progress reporting, batching, and size monitoring.
- `config.py`: Realistic seed data pools (Indian GSTINs, business names, customer names, apparel categories, sizes, cities, return reasons, payment modes).
- `README.md`: This documentation guide.

---

## 🚀 Quick Start

### 1. Check Current Database Status
Inspect existing row counts and on-disk table sizes without modifying anything:
```bash
python Create_demo_data/generate_demo_data.py --status
```

### 2. Generate 5 Lac (500,000) Rows per Table (20 GB Target)
Run the generator with default 5 lac rows per table and 20 GB target footprint:
```bash
python Create_demo_data/generate_demo_data.py --rows-per-table 500000 --target-gb 20
```

### 3. Clean Reset & Fresh Generation
If you want to truncate existing demo records first (using safe `CASCADE TRUNCATE`) and generate fresh:
```bash
python Create_demo_data/generate_demo_data.py --clean --rows-per-table 500000 --target-gb 20
```

### 4. Custom Database Connection
The script automatically reads connection settings from `core/db.py` or your environment variables (`DATABASE_URL`, `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`). 

You can also pass connection flags directly:
```bash
python Create_demo_data/generate_demo_data.py \
  --db-host localhost \
  --db-port 5432 \
  --db-name purchase_tracker \
  --db-user postgres \
  --db-password Password123 \
  --clean --rows-per-table 500000 --target-gb 20
```

---

## ⚙️ Command-Line Arguments Reference

| Flag | Short | Default | Description |
| :--- | :--- | :--- | :--- |
| `--rows-per-table` | `-r` | `500000` | Minimum number of rows to generate per main table (minimum: 500,000). |
| `--target-gb` | `-g` | `20.0` | Target total database disk footprint in Gigabytes. |
| `--batch-size` | `-b` | `50000` | In-memory buffer batch size streamed per `COPY` transaction. |
| `--clean` | `-c` | `False` | Truncates all demo tables (`CASCADE`) and resets serial IDs before generation. |
| `--status` | `-s` | `False` | Displays current row counts and disk sizes for all tables and exits. |
| `--no-padding` | | `False` | Disables text payload padding (generates compact rows without expanding to 20 GB). |
| `--rebuild-cache` | | `False` | Automatically recomputes reporting caches and dashboard snapshots after loading. |
| `--db-url` | | `None` | Custom PostgreSQL URI string (e.g. `postgresql://user:pass@host:5432/dbname`). |

---

## 📊 Populated Tables & Data Distribution

When run with `--rows-per-table 500000`:

| Table Name | Generated Rows | Relational Role |
| :--- | :--- | :--- |
| `parties` | 500,000 | Suppliers/Vendors with valid-format GSTINs, addresses, contacts |
| `customers` | 500,000 | Retail and wholesale customers |
| `items` | 500,000 | Catalog master items across 10 apparel departments with HSN codes |
| `vouchers` | 500,000 | Tally accounting vouchers (Purchase, Sales, Receipt, Payment, etc.) |
| `voucher_entries` | **1,000,000** | Balanced double-entry ledger debit & credit entries |
| `purchases_header` | 500,000 | Purchase bills linked to parties and vouchers |
| `products` | 500,000 | Inventory batches with buy prices, margins, quantities |
| `purchase_item` | 500,000 | Barcoded inventory units (`100000000001` - `100000500000`) |
| `purchase_payments` | 500,000 | Purchase settlement and GST tax breakdown |
| `sales` | 500,000 | Counter and credit invoices linked to customers and vouchers |
| `sold_items` | 500,000 | Invoice item lines with cost, sale price, and profit |
| `sold_item_barcodes`| 500,000 | Barcode links connecting sold items to purchased barcodes |
| `sales_payments` | 500,000 | Payment breakdowns (Cash, Online, UPI, Discounts) |
| `sales_return_items`| 500,000 | Customer return bills with itemized reasons |
| `purchase_return_items`| 500,000 | Vendor return consignments and debit notes |
| `replace_bills` | 500,000 | Exchange/Replacement bill headers |
| `replace_bill_items`| 500,000 | Old vs new replacement item lines |
| `stock_items` | 500,000 | Stock item asset registry |
| `stock_ledger` | 500,000 | Stock movements (quantity in/out, valuation) |
| `old_data` | 500,000 | Legacy purchase migration data with unique IDs |
| **TOTAL** | **~10,500,000 rows** | **Fully linked, consistent ERP database** |

---

## 🔍 Verification Queries (PostgreSQL)

You can verify the database size and row counts at any time in `psql` or pgAdmin:

### Total Database Size:
```sql
SELECT pg_size_pretty(pg_database_size(current_database())) AS total_db_size;
```

### Table Breakdown with Indexes:
```sql
SELECT 
    relname AS table_name,
    n_live_tup AS estimated_rows,
    pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
    pg_size_pretty(pg_relation_size(relid)) AS table_size,
    pg_size_pretty(pg_total_relation_size(relid) - pg_relation_size(relid)) AS index_size
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC;
```
