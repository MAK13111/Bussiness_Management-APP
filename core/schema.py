import os

from core.db import get_conn


# The full Postgres DDL you exported (db_structpost.txt), lightly trimmed
# (see schema.sql's header) and saved alongside this file. Every statement
# in it is idempotent (CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT
# EXISTS / INSERT ... ON CONFLICT DO NOTHING), so running it against an
# already-initialised database is a safe no-op -- exactly like the old
# init_schema() was.
SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "schema.sql")


def init_schema():
    with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
        sql = f.read()

    with get_conn() as conn:
        # Raw psycopg2 cursor, not the sqlite-compat wrapper: this file is
        # plain Postgres SQL (uses %-free syntax, real ON CONFLICT clauses,
        # etc.) and psycopg2 is fine executing many ';'-separated
        # statements in one call as long as there are no bound parameters.
        cur = conn.cursor()
        cur.execute(sql)


def migrate_schema():
    """Idempotent ALTERs for databases that pre-date new columns added to
    schema.sql. Designed to be safe to run on every startup -- every
    statement here is ADD COLUMN IF NOT EXISTS / DROP COLUMN IF EXISTS.
    """
    statements = [
        "ALTER TABLE dashboard_data DROP COLUMN IF EXISTS financial_summary_json",
        "ALTER TABLE dashboard_data ADD COLUMN IF NOT EXISTS total_receivable NUMERIC(18,2) DEFAULT 0",
        "ALTER TABLE dashboard_data ADD COLUMN IF NOT EXISTS total_payable NUMERIC(18,2) DEFAULT 0",
        "ALTER TABLE dashboard_data ADD COLUMN IF NOT EXISTS stock_qty NUMERIC(18,2) DEFAULT 0",
        "ALTER TABLE dashboard_data ADD COLUMN IF NOT EXISTS stock_value NUMERIC(18,2) DEFAULT 0",
        "ALTER TABLE dashboard_data ADD COLUMN IF NOT EXISTS snapshot_updated_at TIMESTAMP",
        "ALTER TABLE purchase_payments ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'completed'",
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS gross_before_discount NUMERIC(18,2) DEFAULT 0",
        """CREATE TABLE IF NOT EXISTS thermal_printer_settings (
            id          INTEGER PRIMARY KEY,
            enabled     SMALLINT DEFAULT 0,
            vendor_id   VARCHAR(10) DEFAULT '',
            product_id  VARCHAR(10) DEFAULT '',
            paper_width INTEGER DEFAULT 80,
            auto_cut    SMALLINT DEFAULT 1,
            CONSTRAINT thermal_printer_settings_single_row CHECK (id = 1)
        )""",
        "INSERT INTO thermal_printer_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING",
        """CREATE TABLE IF NOT EXISTS reports_stats_cache (
            mode                 VARCHAR(10) PRIMARY KEY,
            purchase_count       BIGINT DEFAULT 0,
            purchase_qty         NUMERIC(18,2) DEFAULT 0,
            purchase_buy_total   NUMERIC(18,2) DEFAULT 0,
            purchase_sell_total  NUMERIC(18,2) DEFAULT 0,
            purchase_profit      NUMERIC(18,2) DEFAULT 0,
            sale_count           BIGINT DEFAULT 0,
            sale_qty             NUMERIC(18,2) DEFAULT 0,
            sale_cost_total      NUMERIC(18,2) DEFAULT 0,
            sale_sell_total      NUMERIC(18,2) DEFAULT 0,
            sale_profit          NUMERIC(18,2) DEFAULT 0,
            last_updated         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        "INSERT INTO reports_stats_cache (mode) SELECT 'all' WHERE NOT EXISTS (SELECT 1 FROM reports_stats_cache WHERE mode = 'all')",
        "INSERT INTO reports_stats_cache (mode) SELECT 'cash' WHERE NOT EXISTS (SELECT 1 FROM reports_stats_cache WHERE mode = 'cash')",
        "INSERT INTO reports_stats_cache (mode) SELECT 'credit' WHERE NOT EXISTS (SELECT 1 FROM reports_stats_cache WHERE mode = 'credit')",
        """CREATE TABLE IF NOT EXISTS monthly_stats_cache (
            year         INTEGER NOT NULL,
            month        INTEGER NOT NULL,
            purchases    NUMERIC(18,2) DEFAULT 0,
            sales        NUMERIC(18,2) DEFAULT 0,
            profit       NUMERIC(18,2) DEFAULT 0,
            items_sold   NUMERIC(18,2) DEFAULT 0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (year, month)
        )""",
        """CREATE TABLE IF NOT EXISTS daily_profit_cache (
            sale_date    DATE PRIMARY KEY,
            item_count   BIGINT DEFAULT 0,
            qty_sold     NUMERIC(18,2) DEFAULT 0,
            buy_total    NUMERIC(18,2) DEFAULT 0,
            sell_total   NUMERIC(18,2) DEFAULT 0,
            profit       NUMERIC(18,2) DEFAULT 0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        # NOTE: CREATE INDEX statements have been moved to run_background_startup_tasks()
        # because they are slow on large tables (especially GIN trigram indexes).
        # The app serves requests correctly while indexes are being built in the background.
        "UPDATE ledgers SET group_id = (SELECT id FROM account_groups WHERE name='Indirect Expenses') WHERE name = 'Discount Allowed' AND group_id IS NULL",
        "UPDATE ledgers SET group_id = (SELECT id FROM account_groups WHERE name='Indirect Income') WHERE name = 'Discount Received' AND group_id IS NULL",
        # ── Old Data migration (added for old_data feature) ───────────────────
        # Ensure any existing unique constraint/index on item_code is removed
        "ALTER TABLE IF EXISTS old_data DROP CONSTRAINT IF EXISTS old_data_item_code_key",
        "DROP INDEX IF EXISTS idx_old_data_item_code_unique",
        # Create old_data table for existing databases (new DBs get it from schema.sql)
        """CREATE TABLE IF NOT EXISTS old_data (
            uniqee_id     BIGINT UNIQUE,
            id            BIGSERIAL PRIMARY KEY,
            item_code     TEXT NOT NULL,
            size          TEXT DEFAULT '',
            buy_mrp       NUMERIC(18,2) DEFAULT 0,
            sell_mrp      NUMERIC(18,2) DEFAULT 0,
            remaining     NUMERIC(18,2) DEFAULT 0,
            sold          NUMERIC(18,2) DEFAULT 0,
            imported_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_return     SMALLINT DEFAULT 0
        )""",
        "ALTER TABLE old_data ADD COLUMN IF NOT EXISTS uniqee_id BIGINT",
        "ALTER TABLE old_data ADD COLUMN IF NOT EXISTS is_return SMALLINT DEFAULT 0",
        "ALTER TABLE old_data ADD COLUMN IF NOT EXISTS size TEXT DEFAULT ''",
        # NOTE: idx_old_data_uniqee_id and idx_old_data_item_code built in background (run_background_startup_tasks)
        # Add old_data_imported and old_data_exact_imported flags to app_state
        "ALTER TABLE app_state ADD COLUMN IF NOT EXISTS old_data_imported BOOLEAN DEFAULT FALSE",
        "ALTER TABLE app_state ADD COLUMN IF NOT EXISTS old_data_exact_imported BOOLEAN DEFAULT FALSE",
        # Remove foreign key constraint on sold_items.product_id so it can store old_data uniqee_id
        "ALTER TABLE sold_items DROP CONSTRAINT IF EXISTS sold_items_product_id_fkey",
        # Add is_old column to sold_items: 1 for old_data, 0 for regular products
        "ALTER TABLE sold_items ADD COLUMN IF NOT EXISTS is_old SMALLINT DEFAULT 0",
        # Add actual_price column to sold_items: carried over from older app versions
        # so that backup files containing this column can be imported without error
        "ALTER TABLE sold_items ADD COLUMN IF NOT EXISTS actual_price NUMERIC(18,2) DEFAULT 0",
        "CREATE INDEX IF NOT EXISTS idx_purchase_item_barcode ON purchase_item(barcode_no)",
        "CREATE INDEX IF NOT EXISTS idx_old_data_item_code_trim ON old_data(LOWER(TRIM(item_code)))",
        # Add Barcode column to old_data (new column from updated Excel)
        "ALTER TABLE old_data ADD COLUMN IF NOT EXISTS barcode BIGINT",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_old_data_barcode ON old_data(barcode) WHERE barcode IS NOT NULL",
        # Force re-import so the new barcode column gets populated from the updated Excel file
        "UPDATE app_state SET old_data_exact_imported = FALSE WHERE id = 1 AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'old_data' AND column_name = 'barcode')",
    ]

    with get_conn() as conn:
        cur = conn.cursor()
        # Prevent any single migration statement from blocking startup forever.
        # If another process holds a lock on the table, we fail fast (5s) instead
        # of waiting indefinitely. The savepoint loop below handles each failure
        # gracefully so one missed ALTER doesn't abort the rest.
        cur.execute("SET lock_timeout = '5s'")
        cur.execute("SET statement_timeout = '30s'")
        for stmt in statements:
            try:
                conn.savepoint("migration_step")
                cur.execute(stmt)
                conn.release_savepoint("migration_step")
            except Exception:
                conn.rollback_to_savepoint("migration_step")

    # NOTE: reports cache recompute and old_data Excel import are intentionally
    # NOT called here anymore.  They are slow on large datasets and would block
    # the server from starting.  Call run_background_startup_tasks() in a
    # background thread after migrate_schema() returns (see app.py).


def run_background_startup_tasks():
    """Run slow startup tasks in a background thread so the web server can
    start accepting requests immediately.

    Tasks performed (in order):
      0. Build missing indexes (CREATE INDEX IF NOT EXISTS) and extensions --
         these are idempotent and skipped instantly when already present, but
         can take minutes on large tables the very first time.
      1. Full reports cache recompute (reports_stats_cache, monthly_stats_cache,
         daily_profit_cache) -- can take seconds/minutes on large datasets.
      2. old_data Excel import -- reads Old_Data/old_purchase_data.xlsx and
         bulk-inserts into PostgreSQL; skipped when already done.

    This function is designed to be run in a daemon thread started by app.py
    right after init_app() returns.  It is safe to call more than once -- each
    sub-task is guarded by its own idempotency check.
    """
    print("[startup] Background startup tasks starting...")

    # Task 0: Build indexes and extensions that are slow on large tables.
    # These use a dedicated raw psycopg2 connection with autocommit so each
    # statement commits on its own (required by some DDL on Postgres) and a
    # failure in one index does not abort the others.
    _index_statements = [
        "CREATE EXTENSION IF NOT EXISTS pg_trgm",

        # ── Sales performance (date-wise listing, pagination) ────────────────
        # Primary sort index: sales date DESC + sale_id DESC
        "CREATE INDEX IF NOT EXISTS idx_sales_date_id ON sales (date DESC, sale_id DESC)",
        # Partial index for is_return=0 filter (avoids full scan on COALESCE)
        "CREATE INDEX IF NOT EXISTS idx_sold_items_active ON sold_items (sale_id) WHERE is_return IS DISTINCT FROM 1",
        # FK join index: sold_items.sale_id (critical for the bills-to-items join)
        "CREATE INDEX IF NOT EXISTS idx_sold_items_sale_id ON sold_items (sale_id)",
        # Status filter index for Cash/Credit split
        "CREATE INDEX IF NOT EXISTS idx_sales_status_date ON sales (status, date DESC, sale_id DESC)",

        # ── Purchases performance (date-wise listing, pagination) ────────────
        # Primary sort index: purchases_header date DESC + id DESC
        "CREATE INDEX IF NOT EXISTS idx_purchases_header_date_id ON purchases_header (date DESC, id DESC)",
        # Products FK join index
        "CREATE INDEX IF NOT EXISTS idx_products_purchase_id ON products (purchase_id)",
        # Status + date for Cash/Credit filter
        "CREATE INDEX IF NOT EXISTS idx_purchases_status_date ON purchases_header (status, date DESC, id DESC)",
        # Composite index for name+department filter
        "CREATE INDEX IF NOT EXISTS idx_products_name_dept ON products (item_name, department)",

        # ── Search (trigram fuzzy search) ────────────────────────────────────
        "CREATE INDEX IF NOT EXISTS idx_products_name_trgm ON products USING GIN (item_name gin_trgm_ops)",
        "CREATE INDEX IF NOT EXISTS idx_sold_items_name_trgm ON sold_items USING GIN (item_name gin_trgm_ops)",

        # ── Items master table ───────────────────────────────────────────────
        "CREATE INDEX IF NOT EXISTS idx_items_name_size ON items (name, size)",
        "CREATE INDEX IF NOT EXISTS idx_items_name_lower ON items (LOWER(name))",
        # products.item_name for the GROUP BY in /api/items stock aggregate
        "CREATE INDEX IF NOT EXISTS idx_products_item_name ON products (item_name)",
        "CREATE INDEX IF NOT EXISTS idx_products_item_name_dept ON products (item_name, department)",

        "CREATE INDEX IF NOT EXISTS idx_vouchers_type_number ON vouchers(voucher_type_id, voucher_number)",

        # ── Tally / Accounting reports ───────────────────────────────────────
        # Covering indexes so PostgreSQL can satisfy SUM(debit)/SUM(credit)
        # aggregates in trial balance / balance sheet with index-only scans,
        # avoiding expensive heap fetches on large voucher_entries tables.
        """CREATE INDEX IF NOT EXISTS idx_voucher_entries_lid_cov
            ON voucher_entries(ledger_id, voucher_id)
            INCLUDE (debit, credit)""",
        """CREATE INDEX IF NOT EXISTS idx_voucher_entries_vid_cov
            ON voucher_entries(voucher_id)
            INCLUDE (debit, credit)""",
        # Composite index so ORDER BY v.date DESC, v.id DESC is satisfied without sort.
        "CREATE INDEX IF NOT EXISTS idx_vouchers_date_id ON vouchers(date DESC, id DESC)",

        # ── Old data & Barcodes ─────────────────────────────────────────────
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_old_data_uniqee_id ON old_data(uniqee_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_old_data_barcode ON old_data(barcode) WHERE barcode IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS idx_old_data_item_code ON old_data(LOWER(item_code))",
        "CREATE INDEX IF NOT EXISTS idx_old_data_item_code_trim ON old_data(LOWER(TRIM(item_code)))",
        "CREATE INDEX IF NOT EXISTS idx_purchase_item_barcode ON purchase_item(barcode_no)",
    ]
    try:
        import psycopg2
        from core.db import DATABASE_URL, PG_CONFIG
        raw = psycopg2.connect(DATABASE_URL) if DATABASE_URL else psycopg2.connect(**PG_CONFIG)
        raw.autocommit = True  # each statement is its own transaction
        raw_cur = raw.cursor()
        for stmt in _index_statements:
            try:
                raw_cur.execute(stmt)
                print(f"[startup] Index OK: {stmt[:60].strip()}...")
            except Exception as idx_exc:
                print(f"[startup] Index skipped (non-fatal): {idx_exc}")
        raw.close()
        print("[startup] Index/extension build complete.")
    except Exception as exc:
        print(f"[startup] Index build failed (non-fatal): {exc}")

    # Task 1: Recompute all cache tables (reports + monthly + daily).
    try:
        import core.reports_cache as reports_cache
        from core.db import get_conn
        with get_conn() as conn:
            reports_cache.recompute_all(conn)
        print("[startup] Reports cache recompute complete.")
    except Exception as exc:
        print(f"[startup] Reports cache recompute failed (non-fatal): {exc}")

    # Task 2: Import old_data Excel file if not already done.
    try:
        import_old_data_if_needed()
        print("[startup] old_data import check complete.")
    except Exception as exc:
        print(f"[startup] old_data import failed (non-fatal): {exc}")

    print("[startup] Background startup tasks finished.")


def import_old_data_if_needed(force=False):
    """Import Old_Data/old_purchase_data.xlsx into the `old_data` PostgreSQL table.

    Adds Uniqee_ID as the first column (5-digit unique integers starting from 10001)
    and Is_return as the last column (default value 0).
    Updates the Excel file if these columns are missing, and writes them to PostgreSQL.

    The xlsx file is expected at: <project_root>/Old_Data/old_purchase_data.xlsx
    Columns: Uniqee_ID | ItemCode | Size | Purchase MRP | Sale MRP | Remaining Pieces | Sold Pieces | Barcode | Is_return
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    xlsx_path = os.path.join(project_root, "Old_Data", "old_purchase_data.xlsx")

    if not os.path.exists(xlsx_path):
        return

    with get_conn() as conn:
        state = conn.execute(
            "SELECT COALESCE((SELECT old_data_exact_imported FROM app_state WHERE id = 1), FALSE) AS exact_done, "
            "COALESCE((SELECT old_data_imported FROM app_state WHERE id = 1), FALSE) AS done"
        ).fetchone()

        has_uniqee_col = conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'old_data' AND column_name = 'uniqee_id'"
        ).fetchone()
        has_barcode_col = conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'old_data' AND column_name = 'barcode'"
        ).fetchone()

        if state and state["exact_done"] and has_uniqee_col and has_barcode_col and not force:
            print("[old_data] Exact xlsx import already done — skipping.")
            return

        try:
            import openpyxl
        except ImportError:
            print("[old_data] openpyxl not installed — skipping import.")
            return

        print("[old_data] Inspecting and preparing old_purchase_data.xlsx...")

        # Step 1: Ensure Excel file contains Uniqee_ID (first column) and Is_return (last column)
        wb_check = openpyxl.load_workbook(xlsx_path, data_only=True)
        ws_check = wb_check.active
        raw_header = [str(c.value).strip() if c.value is not None else "" for c in next(ws_check.iter_rows(min_row=1, max_row=1))]

        has_uniqee = any("uniqee" in h.lower() for h in raw_header)
        has_return = any("is_return" in h.lower() or h.lower() == "return" or "is return" in h.lower() for h in raw_header)

        excel_updated = False
        if not (has_uniqee and has_return):
            print("[old_data] Updating Excel file to add Uniqee_ID (first column) and Is_return (last column)...")
            if not has_uniqee:
                ws_check.insert_cols(1)
                ws_check.cell(row=1, column=1, value="Uniqee_ID")
                excel_updated = True

            last_col = ws_check.max_column
            h_last = str(ws_check.cell(row=1, column=last_col).value or "").strip().lower()
            if not ("return" in h_last):
                last_col = last_col + 1
                ws_check.cell(row=1, column=last_col, value="Is_return")
                excel_updated = True

            # Assign 5-digit unique integer IDs starting at 10001, and default Is_return = 0
            cur_id = 10001
            for r_idx in range(2, ws_check.max_row + 1):
                val_u = ws_check.cell(row=r_idx, column=1).value
                if val_u is None or str(val_u).strip() == "":
                    ws_check.cell(row=r_idx, column=1, value=cur_id)
                    cur_id += 1
                else:
                    try:
                        cur_id = max(cur_id, int(val_u) + 1)
                    except (ValueError, TypeError):
                        ws_check.cell(row=r_idx, column=1, value=cur_id)
                        cur_id += 1

                val_r = ws_check.cell(row=r_idx, column=last_col).value
                if val_r is None or str(val_r).strip() == "":
                    ws_check.cell(row=r_idx, column=last_col, value=0)

            if excel_updated:
                try:
                    wb_check.save(xlsx_path)
                    print("[old_data] Excel file successfully updated with Uniqee_ID and Is_return.")
                except Exception as ex:
                    print(f"[old_data] Notice: Could not save Excel file directly ({ex}), proceeding with in-memory data.")

        wb_check.close()

        # Step 2: Read Excel data with fast read-only loader
        wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
        ws = wb.active

        header = [str(c.value).strip() if c.value is not None else "" for c in next(ws.iter_rows(min_row=1, max_row=1))]
        header_lower = [h.lower() for h in header]

        def _col(name):
            for h in header_lower:
                if name.lower() in h:
                    return header_lower.index(h)
            return None

        idx_uniqee    = _col("uniqee")
        idx_code      = result if (result := _col("itemcode"))   is not None else 1
        # Positional fallbacks assume the NEW 9-column layout:
        #   0:Uniqee_ID  1:ItemCode  2:Size  3:Purchase MRP  4:Sale MRP
        #   5:Remaining  6:Sold  7:Barcode  8:Is_return
        # If the expected layout changes again, update these defaults AND the docstring together.
        idx_size      = _col("size")  # optional — None if column absent (old xlsx without Size)
        idx_buy       = result if (result := _col("purchase"))   is not None else 3  # was 2 pre-size
        idx_sell      = result if (result := _col("sale"))       is not None else 4  # was 3
        idx_remaining = result if (result := _col("remaining"))  is not None else 5  # was 4
        idx_sold      = result if (result := _col("sold"))       is not None else 6  # was 5
        idx_barcode   = result if (result := _col("barcode"))    is not None else None  # new column
        idx_return    = result if (result := _col("return"))     is not None else (len(header) - 1)

        # Step 3: Recreate old_data table in Postgres to ensure exact column order
        # First column: uniqee_id, Last column: is_return. barcode is a dedicated scan column.
        conn.execute("DROP TABLE IF EXISTS old_data CASCADE")
        conn.execute("""
            CREATE TABLE old_data (
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
            )
        """)
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_old_data_uniqee_id ON old_data(uniqee_id)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_old_data_barcode ON old_data(barcode) WHERE barcode IS NOT NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_old_data_item_code ON old_data(LOWER(item_code))")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_old_data_item_code_trim ON old_data(LOWER(TRIM(item_code)))")
        conn.commit()

        def _safe_float(val):
            if val is None:
                return 0.0
            try:
                return float(val)
            except (ValueError, TypeError):
                return 0.0

        def _safe_int(val, default=0):
            if val is None:
                return default
            try:
                return int(val)
            except (ValueError, TypeError):
                return default

        inserted = 0
        skipped  = 0
        batch    = []  # list of tuples: (uniqee_id, item_code, size, buy_mrp, sell_mrp, remaining, sold, barcode, is_return)
        BATCH_SIZE = 1000
        fallback_uniqee_id = 10001

        def _flush(rows_to_insert):
            if not rows_to_insert:
                return
            import psycopg2.extras as _extras
            raw_cur = conn.cursor()
            _extras.execute_values(
                raw_cur,
                """
                INSERT INTO old_data (uniqee_id, item_code, size, buy_mrp, sell_mrp, remaining, sold, barcode, is_return)
                VALUES %s
                ON CONFLICT DO NOTHING
                """,
                rows_to_insert,
                template="(%s, %s, %s, %s, %s, %s, %s, %s, %s)"
            )
            conn.commit()

        for row_cells in ws.iter_rows(min_row=2, values_only=True):
            try:
                item_code = str(row_cells[idx_code]).strip() if (idx_code < len(row_cells) and row_cells[idx_code] is not None) else ""
                if not item_code or item_code.lower() == "none":
                    skipped += 1
                    continue

                if idx_uniqee is not None and idx_uniqee < len(row_cells) and row_cells[idx_uniqee] is not None:
                    try:
                        u_id = int(row_cells[idx_uniqee])
                    except (ValueError, TypeError):
                        u_id = fallback_uniqee_id
                else:
                    u_id = fallback_uniqee_id
                fallback_uniqee_id = max(fallback_uniqee_id + 1, u_id + 1)

                size_val  = str(row_cells[idx_size]).strip() if (idx_size is not None and idx_size < len(row_cells) and row_cells[idx_size] is not None) else ""
                buy_mrp   = _safe_float(row_cells[idx_buy]) if idx_buy < len(row_cells) else 0.0
                sell_mrp  = _safe_float(row_cells[idx_sell]) if idx_sell < len(row_cells) else 0.0
                remaining = _safe_float(row_cells[idx_remaining]) if idx_remaining < len(row_cells) else 0.0
                sold      = _safe_float(row_cells[idx_sold]) if idx_sold < len(row_cells) else 0.0

                # Read Barcode column — None if absent in this xlsx
                barcode_val = None
                if idx_barcode is not None and idx_barcode < len(row_cells) and row_cells[idx_barcode] is not None:
                    try:
                        barcode_val = int(row_cells[idx_barcode])
                    except (ValueError, TypeError):
                        barcode_val = None

                is_ret = 0
                if idx_return is not None and idx_return < len(row_cells) and row_cells[idx_return] is not None:
                    is_ret = _safe_int(row_cells[idx_return], 0)

                batch.append((u_id, item_code, size_val, buy_mrp, sell_mrp, remaining, sold, barcode_val, is_ret))
                inserted += 1
                if len(batch) >= BATCH_SIZE:
                    _flush(batch)
                    batch = []
            except Exception as e:
                skipped += 1
                try:
                    conn.rollback()
                except Exception:
                    pass
                continue

        _flush(batch)
        wb.close()

        # Mark as imported (both old_data_imported and old_data_exact_imported)
        conn.execute(
            "UPDATE app_state SET old_data_imported = TRUE, old_data_exact_imported = TRUE WHERE id = 1"
        )
        conn.commit()

        stats = conn.execute(
            "SELECT COUNT(*) AS total_rows, "
            "COUNT(DISTINCT item_code) AS distinct_codes, "
            "COUNT(DISTINCT uniqee_id) AS distinct_uniqee_ids, "
            "COALESCE(SUM(remaining),0) AS total_remaining, "
            "COALESCE(SUM(sold),0) AS total_sold "
            "FROM old_data"
        ).fetchone()
        total_rows          = stats["total_rows"]          if stats else inserted
        distinct_codes      = stats["distinct_codes"]      if stats else "?"
        distinct_uniqee_ids = stats["distinct_uniqee_ids"] if stats else "?"
        total_remaining     = stats["total_remaining"]     if stats else "?"
        total_sold          = stats["total_sold"]          if stats else "?"
        print(
            f"[old_data] Import complete: {total_rows} rows stored ({distinct_codes} distinct item codes, "
            f"{distinct_uniqee_ids} unique 5-digit IDs), "
            f"total remaining={total_remaining}, total sold={total_sold}, "
            f"{skipped} rows skipped (blank item_code). "
            f"({inserted} xlsx rows processed)"
        )

        # Update Opening Stock journal entry to match exact imported inventory


def populate_defaults():
    """
    Kept so existing call sites (app startup, etc.) that call
    schema.init_schema() followed by schema.populate_defaults() still
    work unchanged. All default rows this used to insert in Python
    (account groups, ledgers, voucher types, the Cash/Bank accounts) are
    now inserted directly by schema.sql itself via
    'INSERT ... ON CONFLICT DO NOTHING', so there's nothing left to do
    here -- init_schema() already covers it.
    """
    pass
