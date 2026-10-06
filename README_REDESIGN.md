# ERP/POS Database Redesign (v2)

## What changed
- New PostgreSQL schema in `core/schema.sql` (purchases_header, products,
  purchase_item with barcode sentinel, purchase_payments, customers, sales,
  sold_items, sold_item_barcodes, sales_payments; Tally vouchers use
  voucher_type_id FK).
- Routes updated: purchases, sales, items, legacy (borrow/payments),
  dashboard, reports, parties, department, auth, setting, tally, accounting.
- Items catalog + replace bills preserved; min-stock alerts read from products.
- Tally auto-sync on purchase/sale/return via VoucherEngine.
- Old data (SQLite / backups) is NOT auto-migrated.

## Setup
1. Create empty Postgres database.
2. Set DATABASE_URL or PG* env vars (see core/db.py).
3. Run app — init_schema() applies schema.sql idempotently.
4. First visit: create admin via setup form.

## Barcodes
Counter lives on sentinel row: purchase_item.barcode_no = 0, last_barcode starts at 9999.
Always exclude product_id IS NULL from aggregates.
