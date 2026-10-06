#!/usr/bin/env python3
"""
High-Performance Massive Demo Data Generator for ERP Database (PostgreSQL).

Features:
- Resumable: If cancelled or interrupted (Ctrl+C), seamlessly resumes exactly where it stopped.
- Generates at least 500,000 (5 lac) rows per table across all 20+ tables.
- Target volume scaling up to 20 GB+ database footprint using realistic, structured
  transaction payloads, billing metadata, and audit narrations.
- Ultra-high throughput: uses PostgreSQL COPY FROM STDIN streaming (100k+ rows/sec).
- Complete foreign key and relational integrity across all tables.
- Live progress reporting, rows/sec throughput, ETA, and real-time database disk size metrics.
- Resets sequences automatically so future application transactions work without collision.
- Clean reset / wipe option (--clean) using safe CASCADE TRUNCATE.
- Status inspection (--status) to inspect current row counts and disk sizes.
"""

import argparse
import datetime
import io
import math
import os
import random
import sys
import time
from typing import Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras
from psycopg2.extensions import connection, cursor

# Import seed pools and config
try:
    from config import (
        PG_CONFIG, DATABASE_URL, DEPARTMENTS, CATEGORIES_ITEMS, SIZES, UNITS,
        FIRST_NAMES, LAST_NAMES, BUSINESS_SUFFIXES, CITIES, STREETS,
        RETURN_REASONS, PAYMENT_MODES, STATUS_MODES, NARRATIONS
    )
except ImportError:
    from Create_demo_data.config import (
        PG_CONFIG, DATABASE_URL, DEPARTMENTS, CATEGORIES_ITEMS, SIZES, UNITS,
        FIRST_NAMES, LAST_NAMES, BUSINESS_SUFFIXES, CITIES, STREETS,
        RETURN_REASONS, PAYMENT_MODES, STATUS_MODES, NARRATIONS
    )


def get_db_connection(args: argparse.Namespace) -> connection:
    """Establish and tune PostgreSQL connection for bulk loading."""
    conn_params = {}
    if args.db_url or DATABASE_URL:
        db_url = args.db_url or DATABASE_URL
        conn = psycopg2.connect(db_url)
    else:
        conn_params = dict(
            host=args.db_host or PG_CONFIG.get("host", "localhost"),
            port=args.db_port or PG_CONFIG.get("port", "5432"),
            dbname=args.db_name or PG_CONFIG.get("dbname", "purchase_tracker"),
            user=args.db_user or PG_CONFIG.get("user", "postgres"),
            password=args.db_password or PG_CONFIG.get("password", "Password123"),
        )
        conn = psycopg2.connect(**conn_params)

    conn.autocommit = False
    with conn.cursor() as cur:
        # Session performance optimizations for bulk streaming
        cur.execute("SET synchronous_commit = off;")
        cur.execute("SET work_mem = '256MB';")
        cur.execute("SET maintenance_work_mem = '512MB';")
    conn.commit()
    return conn


def get_db_size(conn: connection) -> str:
    """Retrieve human-readable total database size."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()));")
            return cur.fetchone()[0]
    except Exception:
        return "Unknown"


def get_table_count(conn: connection, table: str) -> int:
    """Retrieve exact row count in a table."""
    with conn.cursor() as cur:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table};")
            row = cur.fetchone()
            return int(row[0]) if row else 0
        except Exception:
            return 0


def get_id_range(conn: connection, table: str, pk_col: str) -> Tuple[int, int]:
    """Retrieve MIN and MAX of an ID column."""
    with conn.cursor() as cur:
        try:
            cur.execute(f"SELECT COALESCE(MIN({pk_col}), 0), COALESCE(MAX({pk_col}), 0) FROM {table};")
            row = cur.fetchone()
            return (int(row[0]), int(row[1])) if row else (0, 0)
        except Exception:
            return (0, 0)


def get_max_id(conn: connection, table: str, pk_col: str) -> int:
    """Retrieve maximum primary key/identifier value in a table."""
    with conn.cursor() as cur:
        try:
            cur.execute(f"SELECT COALESCE(MAX({pk_col}), 0) FROM {table};")
            row = cur.fetchone()
            return int(row[0]) if row and row[0] is not None else 0
        except Exception:
            return 0


def get_table_stats(conn: connection) -> List[Dict]:
    """Retrieve row counts and on-disk size for all application tables efficiently."""
    tables = [
        "parties", "customers", "items", "purchases_header", "products",
        "purchase_item", "purchase_payments", "sales", "sold_items",
        "sold_item_barcodes", "sales_payments", "sales_return_items",
        "purchase_return_items", "replace_bills", "replace_bill_items",
        "vouchers", "voucher_entries", "stock_items", "stock_ledger",
        "old_data"
    ]
    stats = []
    with conn.cursor() as cur:
        for tbl in tables:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {tbl};")
                count = cur.fetchone()[0]
                cur.execute(f"SELECT pg_size_pretty(pg_total_relation_size('{tbl}'));")
                size = cur.fetchone()[0]
                stats.append({"table": tbl, "count": count, "size": size})
            except Exception:
                stats.append({"table": tbl, "count": 0, "size": "N/A"})
    return stats


def print_status(conn: connection):
    """Print current tables status and total database size."""
    stats = get_table_stats(conn)
    total_size = get_db_size(conn)
    print("\n" + "=" * 68)
    print(f"  ERP DATABASE STATUS  |  Total Database Disk Size: {total_size}")
    print("=" * 68)
    print(f"{'Table Name':<28} {'Row Count':>16} {'Disk Size (w/ indexes)':>20}")
    print("-" * 68)
    total_rows = 0
    for s in stats:
        total_rows += s["count"]
        print(f"{s['table']:<28} {s['count']:>16,d} {s['size']:>20}")
    print("-" * 68)
    print(f"{'TOTAL':<28} {total_rows:>16,d} {total_size:>20}")
    print("=" * 68 + "\n")


def clean_database(conn: connection):
    """Truncate existing tables with CASCADE to allow clean generation."""
    print("\n[!] Truncating existing application tables (CASCADE)...")
    tables = [
        "sold_item_barcodes", "sold_items", "sales_payments", "sales_return_items",
        "replace_bill_items", "replace_bills", "purchase_return_items",
        "purchase_payments", "purchase_item", "products", "purchases_header",
        "sales", "stock_ledger", "stock_items", "voucher_entries", "vouchers",
        "customers", "parties", "items", "old_data"
    ]
    with conn.cursor() as cur:
        for tbl in tables:
            try:
                cur.execute(f"TRUNCATE TABLE {tbl} RESTART IDENTITY CASCADE;")
            except Exception as e:
                print(f"    Notice for {tbl}: {e}")
        conn.commit()
    print("[+] All demo tables wiped and sequences reset to 1.\n")


_CHUNK_POOL = None


def get_payload_pool() -> List[str]:
    """Pre-generate diverse, high-entropy tokens to prevent PostgreSQL TOAST LZ compression."""
    global _CHUNK_POOL
    if _CHUNK_POOL is None:
        import hashlib
        pool = []
        for seed in range(500):
            tokens = [hashlib.sha256(f"AUDIT-ERP-PAYLOAD-{seed}-{k}".encode()).hexdigest() for k in range(32)]
            pool.append(" ".join(tokens))
        _CHUNK_POOL = pool
    return _CHUNK_POOL


def generate_payload_chunk(size_bytes: int, seed_id: int) -> str:
    """Generate realistic business filler with high-entropy hashes to guarantee real on-disk footprint."""
    if size_bytes <= 0:
        return ""
    pool = get_payload_pool()
    chunk = pool[seed_id % len(pool)]
    repeats = max(1, math.ceil(size_bytes / len(chunk)))
    result = (f"[AUDIT-TAG-{seed_id:08x}] " + (chunk * repeats))[:size_bytes]
    return result


class FastStreamCopier:
    """Buffers rows in memory and streams directly via COPY FROM STDIN."""

    def __init__(self, conn: connection, table: str, columns: List[str], batch_size: int = 50000):
        self.conn = conn
        self.table = table
        self.columns = columns
        self.batch_size = batch_size
        self.buffer = io.StringIO()
        self.count = 0
        self.total_inserted = 0

    def add_row(self, row_values: List):
        formatted = []
        for val in row_values:
            if val is None:
                formatted.append("\\N")
            elif isinstance(val, (int, float)):
                formatted.append(str(val))
            elif isinstance(val, bool):
                formatted.append("t" if val else "f")
            elif isinstance(val, (datetime.date, datetime.datetime)):
                formatted.append(str(val).split(".")[0])
            else:
                s = str(val).replace("\\", "\\\\").replace("\t", " ").replace("\n", " ").replace("\r", " ")
                formatted.append(s)
        self.buffer.write("\t".join(formatted) + "\n")
        self.count += 1
        if self.count >= self.batch_size:
            self.flush()

    def flush(self):
        if self.count == 0:
            return
        self.buffer.seek(0)
        with self.conn.cursor() as cur:
            cur.copy_from(
                self.buffer,
                self.table,
                columns=self.columns,
                null="\\N",
            )
        self.conn.commit()
        self.total_inserted += self.count
        self.buffer = io.StringIO()
        self.count = 0


def expand_database_payload(conn: connection, target_gb: float, batch_size: int = 50000):
    """Expands existing rows with high-entropy text payloads to reach target disk size at 50,000+ rows/sec."""
    cur_size_str = get_db_size(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT pg_database_size(current_database());")
        cur_bytes = cur.fetchone()[0]
    target_bytes = int(target_gb * (1024 ** 3))
    if cur_bytes >= target_bytes:
        print(f"[✓] Database already at {cur_size_str} (>= target {target_gb:.1f} GB). No expansion needed.")
        return

    needed_bytes = target_bytes - cur_bytes
    padded_tables = [
        ("vouchers", "id", "narration"),
        ("parties", "party_id", "address"),
        ("replace_bills", "id", "note"),
        ("sales_return_items", "id", "reason"),
        ("purchase_return_items", "id", "reason"),
    ]

    total_padded_rows = sum(get_table_count(conn, tbl) for tbl, _, _ in padded_tables)
    if total_padded_rows == 0:
        return

    bytes_per_row = max(1500, int(needed_bytes / total_padded_rows))
    num_hashes = max(10, int(bytes_per_row / 32))
    print("\n" + "=" * 72)
    print(f"  ULTRA HIGH-SPEED EXPANSION TO REACH >= {target_gb:.1f} GB")
    print(f"  - Current DB Size   : {cur_size_str}")
    print(f"  - Additional Needed : {needed_bytes / (1024**3):.2f} GB")
    print(f"  - Payload / Row     : {bytes_per_row:,d} bytes ({num_hashes} unique hashes) across {total_padded_rows:,d} rows")
    print("=" * 72 + "\n")

    for tbl, pk_col, text_col in padded_tables:
        min_id, max_id = get_id_range(conn, tbl, pk_col)
        count = get_table_count(conn, tbl)
        if count == 0:
            continue
        print(f"[→] In-engine expansion: {tbl}.{text_col} ({count:,d} rows)...")
        t0 = time.time()
        chunk_size = batch_size
        start_id = min_id
        updated = 0
        with conn.cursor() as cur:
            while start_id <= max_id:
                end_id = start_id + chunk_size - 1
                sql = f"""
                    UPDATE {tbl}
                    SET {text_col} = SUBSTRING(COALESCE({text_col}, ''), 1, 80) || 
                                     ' [AUDIT-TAG-' || TO_HEX({pk_col}) || '] ' || 
                                     (SELECT string_agg(MD5({pk_col}::text || '-' || g::text), '') FROM generate_series(1, {num_hashes}) g)
                    WHERE {pk_col} BETWEEN {start_id} AND {end_id};
                """
                cur.execute(sql)
                conn.commit()
                updated += cur.rowcount
                if updated % 50000 == 0 or end_id >= max_id:
                    rate = updated / max(0.01, time.time() - t0)
                    print(f"    --> {tbl}: {updated:,d}/{count:,d} ({(updated/count)*100:.1f}%) | {rate:,.0f} rows/s")
                start_id += chunk_size

    print(f"[✓] High-speed payload expansion complete. Current Size: {get_db_size(conn)}\n")


def generate_all_demo_data(args: argparse.Namespace):
    start_time = time.time()
    min_rows = max(500000, args.rows_per_table)
    target_gb = args.target_gb
    batch_size = args.batch_size

    conn = get_db_connection(args)

    if args.status:
        print_status(conn)
        conn.close()
        return

    if args.clean:
        clean_database(conn)

    # Calculate payload padding to reach target GB across the 5 unindexed text tables
    target_bytes = target_gb * (1024 ** 3)
    estimated_raw = (min_rows * 18) * 350
    extra_needed = max(0, target_bytes - estimated_raw)
    num_padded_tables = 5  # parties, vouchers, sales_return_items, purchase_return_items, replace_bills
    padding_per_row = int(extra_needed / max(1, min_rows * num_padded_tables)) if not args.no_padding else 0

    print("=" * 72)
    print(f"  MASSIVE DEMO DATA GENERATOR FOR ERP DATABASE")
    print(f"  - Minimum Rows Per Table : {min_rows:,d} (>= 5 Lacs)")
    print(f"  - Target Database Size   : {target_gb:.1f} GB")
    print(f"  - Streaming Batch Size   : {batch_size:,d} rows/batch")
    print(f"  - Text Payload Padding   : {padding_per_row} bytes/row")
    print(f"  - Current DB Disk Size   : {get_db_size(conn)}")
    print("=" * 72 + "\n")

    # Ensure pre-requisite departments exist
    with conn.cursor() as cur:
        for dept in DEPARTMENTS:
            cur.execute("INSERT INTO department (name) VALUES (%s) ON CONFLICT (name) DO NOTHING;", (dept,))
        conn.commit()

    base_date = datetime.date(2024, 1, 1)

    try:
        # ──────────────────────────────────────────────────────────────────────────
        # 1. PARTIES
        # ──────────────────────────────────────────────────────────────────────────
        cur_parties = get_table_count(conn, "parties")
        max_p_id = get_max_id(conn, "parties", "party_id")
        if cur_parties >= min_rows:
            print(f"[✓] [1/18] PARTIES: {cur_parties:,d}/{min_rows:,d} rows already present. Skipping.")
        else:
            needed = min_rows - cur_parties
            print(f"\n[→] [1/18] PARTIES: Resuming at row {cur_parties + 1:,d} -> {min_rows:,d} ({needed:,d} remaining)...")
            t0 = time.time()
            copier = FastStreamCopier(
                conn, "parties",
                ["party_id", "party_name", "contact_no", "address", "gst_no", "status", "created_at"],
                batch_size
            )
            for i in range(cur_parties + 1, min_rows + 1):
                p_id = max_p_id + (i - cur_parties)
                city, state, pin, st_code = CITIES[i % len(CITIES)]
                fname = FIRST_NAMES[i % len(FIRST_NAMES)]
                lname = LAST_NAMES[(i // len(FIRST_NAMES)) % len(LAST_NAMES)]
                suffix = BUSINESS_SUFFIXES[i % len(BUSINESS_SUFFIXES)]
                party_name = f"{fname} {lname} {suffix} #{p_id}"
                contact_no = f"9{random.randint(100000000, 999999999)}"
                street = STREETS[i % len(STREETS)]
                pad = generate_payload_chunk(padding_per_row, p_id)
                address = f"Shop #{i % 999 + 1}, {street}, {city}, {state} - {pin}. {pad}"
                pan = f"AAAPL{p_id:04d}K"[-10:] if p_id <= 9999 else f"A{p_id:09d}"[-10:]
                gst_no = f"{st_code}{pan}1Z{p_id % 9}"
                status = "Credit" if i % 3 == 0 else "Cash"
                created_at = datetime.datetime(2024, 1, 1) + datetime.timedelta(minutes=i * 2 % 1000000)

                copier.add_row([p_id, party_name, contact_no, address, gst_no, status, created_at])
                if i % 50000 == 0 or i == min_rows:
                    rate = (i - cur_parties) / max(0.01, time.time() - t0)
                    print(f"    --> Parties: {i:,d}/{min_rows:,d} ({(i/min_rows)*100:.1f}%) | {rate:,.0f} rows/s")
            copier.flush()

        # ──────────────────────────────────────────────────────────────────────────
        # 2. CUSTOMERS
        # ──────────────────────────────────────────────────────────────────────────
        cur_cust = get_table_count(conn, "customers")
        max_c_id = get_max_id(conn, "customers", "customer_id")
        if cur_cust >= min_rows:
            print(f"[✓] [2/18] CUSTOMERS: {cur_cust:,d}/{min_rows:,d} rows already present. Skipping.")
        else:
            needed = min_rows - cur_cust
            print(f"\n[→] [2/18] CUSTOMERS: Resuming at row {cur_cust + 1:,d} -> {min_rows:,d} ({needed:,d} remaining)...")
            t0 = time.time()
            copier = FastStreamCopier(conn, "customers", ["customer_id", "customer_name", "customer_no", "status"], batch_size)
            for i in range(cur_cust + 1, min_rows + 1):
                c_id = max_c_id + (i - cur_cust)
                fname = FIRST_NAMES[i % len(FIRST_NAMES)]
                lname = LAST_NAMES[(i // len(FIRST_NAMES)) % len(LAST_NAMES)]
                cname = f"{fname} {lname} (Cust-{c_id})"
                cno = f"8{random.randint(100000000, 999999999)}"
                status = 1 if i % 10 == 0 else 0
                copier.add_row([c_id, cname, cno, status])
                if i % 50000 == 0 or i == min_rows:
                    rate = (i - cur_cust) / max(0.01, time.time() - t0)
                    print(f"    --> Customers: {i:,d}/{min_rows:,d} ({(i/min_rows)*100:.1f}%) | {rate:,.0f} rows/s")
            copier.flush()

        # ──────────────────────────────────────────────────────────────────────────
        # 3. ITEMS (Catalog Master)
        # ──────────────────────────────────────────────────────────────────────────
        cur_items = get_table_count(conn, "items")
        max_it_id = get_max_id(conn, "items", "id")
        if cur_items >= min_rows:
            print(f"[✓] [3/18] ITEMS: {cur_items:,d}/{min_rows:,d} rows already present. Skipping.")
        else:
            needed = min_rows - cur_items
            print(f"\n[→] [3/18] ITEMS: Resuming at row {cur_items + 1:,d} -> {min_rows:,d} ({needed:,d} remaining)...")
            t0 = time.time()
            copier = FastStreamCopier(
                conn, "items",
                ["id", "name", "department", "hsn", "unit", "size", "defaultmargin", "defaultgst", "min_stock", "createdat"],
                batch_size
            )
            for i in range(cur_items + 1, min_rows + 1):
                it_id = max_it_id + (i - cur_items)
                dept = DEPARTMENTS[i % len(DEPARTMENTS)]
                cat_items = CATEGORIES_ITEMS.get(dept, ["Apparel Item"])
                base_name = cat_items[i % len(cat_items)]
                pad = f" [SKU-{it_id:07d}]"
                name = f"{base_name}{pad}"
                hsn = f"{6100 + (i % 99):04d}"
                unit = UNITS[i % len(UNITS)]
                size = SIZES[i % len(SIZES)]
                margin = round(15.0 + (i % 30), 2)
                gst = 5.0 if i % 2 == 0 else 12.0
                min_stock = float(5 + (i % 20))
                created_at = datetime.datetime(2024, 1, 1) + datetime.timedelta(minutes=i % 500000)
                copier.add_row([it_id, name, dept, hsn, unit, size, margin, gst, min_stock, created_at])
                if i % 50000 == 0 or i == min_rows:
                    rate = (i - cur_items) / max(0.01, time.time() - t0)
                    print(f"    --> Items: {i:,d}/{min_rows:,d} ({(i/min_rows)*100:.1f}%) | {rate:,.0f} rows/s")
            copier.flush()

        # ──────────────────────────────────────────────────────────────────────────
        # 4. VOUCHERS
        # ──────────────────────────────────────────────────────────────────────────
        cur_vch = get_table_count(conn, "vouchers")
        max_vch_id = get_max_id(conn, "vouchers", "id")
        if cur_vch >= min_rows:
            print(f"[✓] [4/18] VOUCHERS: {cur_vch:,d}/{min_rows:,d} rows already present. Skipping.")
        else:
            needed = min_rows - cur_vch
            print(f"\n[→] [4/18] VOUCHERS: Resuming at row {cur_vch + 1:,d} -> {min_rows:,d} ({needed:,d} remaining)...")
            t0 = time.time()
            copier = FastStreamCopier(
                conn, "vouchers",
                ["id", "voucher_number", "voucher_type_id", "date", "reference", "narration", "created_by", "is_posted", "created_at"],
                batch_size
            )
            for i in range(cur_vch + 1, min_rows + 1):
                vch_id = max_vch_id + (i - cur_vch)
                vch_num = f"VCH-{vch_id:09d}"
                vch_type = (i % 6) + 1
                vch_date = base_date + datetime.timedelta(days=(i % 900))
                ref = f"REF/24-25/{vch_id:07d}"
                base_narration = NARRATIONS[i % len(NARRATIONS)]
                pad = generate_payload_chunk(padding_per_row, vch_id)
                narration = f"{base_narration} {pad}"
                copier.add_row([vch_id, vch_num, vch_type, vch_date, ref, narration, "Admin", True, vch_date])
                if i % 50000 == 0 or i == min_rows:
                    rate = (i - cur_vch) / max(0.01, time.time() - t0)
                    print(f"    --> Vouchers: {i:,d}/{min_rows:,d} ({(i/min_rows)*100:.1f}%) | {rate:,.0f} rows/s")
            copier.flush()

        # ──────────────────────────────────────────────────────────────────────────
        # 5. VOUCHER ENTRIES (2 rows per voucher)
        # ──────────────────────────────────────────────────────────────────────────
        target_entries = min_rows * 2
        cur_entries = get_table_count(conn, "voucher_entries")
        max_entry_id = get_max_id(conn, "voucher_entries", "id")
        min_v_id, max_v_id = get_id_range(conn, "vouchers", "id")
        vch_span = max(1, max_v_id - min_v_id + 1)
        if cur_entries >= target_entries:
            print(f"[✓] [5/18] VOUCHER_ENTRIES: {cur_entries:,d}/{target_entries:,d} rows already present. Skipping.")
        else:
            needed = target_entries - cur_entries
            start_v_idx = (cur_entries // 2) + 1
            print(f"\n[→] [5/18] VOUCHER_ENTRIES: Resuming at voucher #{start_v_idx:,d} -> {min_rows:,d} ({needed:,d} entries remaining)...")
            t0 = time.time()
            copier = FastStreamCopier(
                conn, "voucher_entries",
                ["id", "voucher_id", "ledger_id", "debit", "credit"],
                batch_size
            )
            entry_id = max_entry_id + 1
            for v_idx in range(start_v_idx, min_rows + 1):
                vch_id = min_v_id + ((v_idx - 1) % vch_span)
                amount = round(500.0 + (vch_id % 5000) * 1.5, 2)
                copier.add_row([entry_id, vch_id, 1 if v_idx % 2 == 0 else 5, amount, 0.0])
                entry_id += 1
                copier.add_row([entry_id, vch_id, 4 if v_idx % 2 == 0 else 2, 0.0, amount])
                entry_id += 1
                if v_idx % 25000 == 0 or v_idx == min_rows:
                    rate = (entry_id - (max_entry_id + 1)) / max(0.01, time.time() - t0)
                    print(f"    --> Voucher Entries: {(v_idx * 2):,d}/{target_entries:,d} | {rate:,.0f} rows/s")
            copier.flush()

        # ──────────────────────────────────────────────────────────────────────────
        # 6. PURCHASES HEADER
        # ──────────────────────────────────────────────────────────────────────────
        min_party_id, max_party_id = get_id_range(conn, "parties", "party_id")
        party_span = max(1, max_party_id - min_party_id + 1)
        cur_ph = get_table_count(conn, "purchases_header")
        max_ph_id = get_max_id(conn, "purchases_header", "id")
        if cur_ph >= min_rows:
            print(f"[✓] [6/18] PURCHASES_HEADER: {cur_ph:,d}/{min_rows:,d} rows already present. Skipping.")
        else:
            needed = min_rows - cur_ph
            print(f"\n[→] [6/18] PURCHASES_HEADER: Resuming at row {cur_ph + 1:,d} -> {min_rows:,d} ({needed:,d} remaining)...")
            t0 = time.time()
            copier = FastStreamCopier(
                conn, "purchases_header",
                ["id", "purchase_id", "party_id", "date", "due_date", "status", "invoice_no", "voucher_id", "created_at"],
                batch_size
            )
            for i in range(cur_ph + 1, min_rows + 1):
                ph_id = max_ph_id + (i - cur_ph)
                party_id = min_party_id + ((i - 1) % party_span)
                voucher_id = min_v_id + ((i - 1) % vch_span)
                p_date = base_date + datetime.timedelta(days=(i % 900))
                due_date = p_date + datetime.timedelta(days=30)
                status = STATUS_MODES[i % len(STATUS_MODES)]
                inv_no = f"INV/PUR/{2024 + (i % 2)}/{ph_id:07d}"
                copier.add_row([ph_id, ph_id, party_id, p_date, due_date, status, inv_no, voucher_id, p_date])
                if i % 50000 == 0 or i == min_rows:
                    rate = (i - cur_ph) / max(0.01, time.time() - t0)
                    print(f"    --> Purchases Header: {i:,d}/{min_rows:,d} ({(i/min_rows)*100:.1f}%) | {rate:,.0f} rows/s")
            copier.flush()

        # ──────────────────────────────────────────────────────────────────────────
        # 7. PRODUCTS (Inventory Product Batches)
        # ──────────────────────────────────────────────────────────────────────────
        min_ph_id, max_ph_id = get_id_range(conn, "purchases_header", "id")
        ph_span = max(1, max_ph_id - min_ph_id + 1)
        cur_prod = get_table_count(conn, "products")
        max_prod_id = get_max_id(conn, "products", "product_id")
        if cur_prod >= min_rows:
            print(f"[✓] [7/18] PRODUCTS: {cur_prod:,d}/{min_rows:,d} rows already present. Skipping.")
        else:
            needed = min_rows - cur_prod
            print(f"\n[→] [7/18] PRODUCTS: Resuming at row {cur_prod + 1:,d} -> {min_rows:,d} ({needed:,d} remaining)...")
            t0 = time.time()
            copier = FastStreamCopier(
                conn, "products",
                ["product_id", "party_id", "purchase_id", "item_name", "size", "date", "total_buy_price",
                 "unit_price", "department", "margin", "qty", "sold", "remaining", "projected_margin", "status", "created_at"],
                batch_size
            )
            for i in range(cur_prod + 1, min_rows + 1):
                prod_id = max_prod_id + (i - cur_prod)
                party_id = min_party_id + ((i - 1) % party_span)
                purchase_id = min_ph_id + ((i - 1) % ph_span)
                dept = DEPARTMENTS[i % len(DEPARTMENTS)]
                cat_items = CATEGORIES_ITEMS.get(dept, ["Product Item"])
                base_name = cat_items[i % len(cat_items)]
                pad = f" Lot-{prod_id:07d}"
                item_name = f"{base_name}{pad}"
                size = SIZES[i % len(SIZES)]
                p_date = base_date + datetime.timedelta(days=(i % 900))
                qty = float(20 + (i % 50))
                sold = float(i % int(qty))
                remaining = qty - sold
                unit_price = round(250.0 + (i % 1500) * 1.25, 2)
                total_buy_price = round(qty * unit_price, 2)
                margin = round(20.0 + (i % 25), 2)
                proj_margin = round(total_buy_price * (margin / 100.0), 2)
                status = STATUS_MODES[i % len(STATUS_MODES)]
                copier.add_row([
                    prod_id, party_id, purchase_id, item_name, size, p_date, total_buy_price,
                    unit_price, dept, margin, qty, sold, remaining, proj_margin, status, p_date
                ])
                if i % 50000 == 0 or i == min_rows:
                    rate = (i - cur_prod) / max(0.01, time.time() - t0)
                    print(f"    --> Products: {i:,d}/{min_rows:,d} ({(i/min_rows)*100:.1f}%) | {rate:,.0f} rows/s")
            copier.flush()

        # ──────────────────────────────────────────────────────────────────────────
        # 8. PURCHASE ITEM (Barcoded Units)
        # ──────────────────────────────────────────────────────────────────────────
        min_prod_id, max_prod_id = get_id_range(conn, "products", "product_id")
        prod_span = max(1, max_prod_id - min_prod_id + 1)
        cur_pi = get_table_count(conn, "purchase_item") - 1  # Subtract sentinel row
        cur_pi = max(0, cur_pi)
        max_pi_id = get_max_id(conn, "purchase_item", "id")
        max_barcode = get_max_id(conn, "purchase_item", "barcode_no")
        base_barcode = max(100000000000, max_barcode)
        if cur_pi >= min_rows:
            print(f"[✓] [8/18] PURCHASE_ITEM: {cur_pi:,d}/{min_rows:,d} rows already present. Skipping.")
        else:
            needed = min_rows - cur_pi
            print(f"\n[→] [8/18] PURCHASE_ITEM: Resuming at row {cur_pi + 1:,d} -> {min_rows:,d} ({needed:,d} remaining)...")
            t0 = time.time()
            copier = FastStreamCopier(
                conn, "purchase_item",
                ["id", "product_id", "party_id", "item_name", "size", "barcode_no", "buy_price",
                 "sale_price", "margin", "is_available", "sold_at", "is_returned", "last_barcode", "created_at"],
                batch_size
            )
            for i in range(cur_pi + 1, min_rows + 1):
                pi_id = max_pi_id + (i - cur_pi)
                product_id = min_prod_id + ((i - 1) % prod_span)
                party_id = min_party_id + ((i - 1) % party_span)
                dept = DEPARTMENTS[i % len(DEPARTMENTS)]
                cat_items = CATEGORIES_ITEMS.get(dept, ["Item Unit"])
                item_name = cat_items[i % len(cat_items)]
                size = SIZES[i % len(SIZES)]
                barcode_no = base_barcode + (i - cur_pi)
                buy_price = round(300.0 + (i % 1200), 2)
                margin = round(25.0 + (i % 20), 2)
                sale_price = round(buy_price * (1 + margin / 100.0), 2)
                is_avail = "sold" if i % 2 == 0 else "available"
                sold_at = (datetime.datetime(2024, 1, 1) + datetime.timedelta(days=(i % 900))) if is_avail == "sold" else None
                is_returned = 1 if i % 50 == 0 else 0
                created_at = datetime.datetime(2024, 1, 1) + datetime.timedelta(days=(i % 900))

                copier.add_row([
                    pi_id, product_id, party_id, item_name, size, barcode_no, buy_price,
                    sale_price, margin, is_avail, sold_at, is_returned, barcode_no, created_at
                ])
                if i % 50000 == 0 or i == min_rows:
                    rate = (i - cur_pi) / max(0.01, time.time() - t0)
                    print(f"    --> Purchase Items: {i:,d}/{min_rows:,d} ({(i/min_rows)*100:.1f}%) | {rate:,.0f} rows/s")
            copier.flush()

        # ──────────────────────────────────────────────────────────────────────────
        # 9. PURCHASE PAYMENTS
        # ──────────────────────────────────────────────────────────────────────────
        cur_pp = get_table_count(conn, "purchase_payments")
        max_pp_id = get_max_id(conn, "purchase_payments", "id")
        if cur_pp >= min_rows:
            print(f"[✓] [9/18] PURCHASE_PAYMENTS: {cur_pp:,d}/{min_rows:,d} rows already present. Skipping.")
        else:
            needed = min_rows - cur_pp
            print(f"\n[→] [9/18] PURCHASE_PAYMENTS: Resuming at row {cur_pp + 1:,d} -> {min_rows:,d} ({needed:,d} remaining)...")
            t0 = time.time()
            copier = FastStreamCopier(
                conn, "purchase_payments",
                ["id", "purchase_id", "party_id", "is_credit", "mode_of_payment", "total_buy_amount",
                 "total_with_gst", "total_buy_amount_discount", "paid_amount", "remaining_amount",
                 "cgst", "sgst", "igst", "discount", "status"],
                batch_size
            )
            for i in range(cur_pp + 1, min_rows + 1):
                pp_id = max_pp_id + (i - cur_pp)
                purchase_id = min_ph_id + (i - 1)
                party_id = min_party_id + ((i - 1) % party_span)
                is_credit = 1 if i % 3 == 0 else 0
                mode = PAYMENT_MODES[i % len(PAYMENT_MODES)]
                total_buy = round(2000.0 + (i % 10000) * 1.5, 2)
                gst = round(total_buy * 0.05, 2)
                total_with_gst = round(total_buy + gst, 2)
                discount = round(50.0 + (i % 200), 2)
                total_after_disc = round(total_with_gst - discount, 2)
                paid = total_after_disc if not is_credit else round(total_after_disc * 0.5, 2)
                rem = round(total_after_disc - paid, 2)
                status = "completed" if rem == 0 else "pending"

                copier.add_row([
                    pp_id, purchase_id, party_id, is_credit, mode, total_buy, total_with_gst,
                    total_after_disc, paid, rem, round(gst / 2, 2), round(gst / 2, 2), 0.0, discount, status
                ])
                if i % 50000 == 0 or i == min_rows:
                    rate = (i - cur_pp) / max(0.01, time.time() - t0)
                    print(f"    --> Purchase Payments: {i:,d}/{min_rows:,d} ({(i/min_rows)*100:.1f}%) | {rate:,.0f} rows/s")
            copier.flush()

        # ──────────────────────────────────────────────────────────────────────────
        # 10. SALES
        # ──────────────────────────────────────────────────────────────────────────
        min_cust_id, max_cust_id = get_id_range(conn, "customers", "customer_id")
        cust_span = max(1, max_cust_id - min_cust_id + 1)
        cur_sales = get_table_count(conn, "sales")
        max_sale_id = get_max_id(conn, "sales", "sale_id")
        if cur_sales >= min_rows:
            print(f"[✓] [10/18] SALES: {cur_sales:,d}/{min_rows:,d} rows already present. Skipping.")
        else:
            needed = min_rows - cur_sales
            print(f"\n[→] [10/18] SALES: Resuming at row {cur_sales + 1:,d} -> {min_rows:,d} ({needed:,d} remaining)...")
            t0 = time.time()
            copier = FastStreamCopier(
                conn, "sales",
                ["sale_id", "customers_id", "voucher_id", "status", "bill_no", "date",
                 "due_date", "total_buy_price", "total_sale_price", "total_profit", "discount", "created_at"],
                batch_size
            )
            for i in range(cur_sales + 1, min_rows + 1):
                s_id = max_sale_id + (i - cur_sales)
                cust_id = min_cust_id + ((i - 1) % cust_span)
                voucher_id = min_v_id + ((i - 1) % vch_span)
                status = STATUS_MODES[i % len(STATUS_MODES)]
                bill_no = f"BILL/2024/{s_id:08d}"
                s_date = base_date + datetime.timedelta(days=(i % 900))
                due_date = s_date + datetime.timedelta(days=15)
                buy_total = round(800.0 + (i % 4000), 2)
                sale_total = round(buy_total * 1.35, 2)
                profit = round(sale_total - buy_total, 2)
                discount = round(i % 100, 2)

                copier.add_row([
                    s_id, cust_id, voucher_id, status, bill_no, s_date, due_date,
                    buy_total, sale_total, profit, discount, s_date
                ])
                if i % 50000 == 0 or i == min_rows:
                    rate = (i - cur_sales) / max(0.01, time.time() - t0)
                    print(f"    --> Sales: {i:,d}/{min_rows:,d} ({(i/min_rows)*100:.1f}%) | {rate:,.0f} rows/s")
            copier.flush()

        # ──────────────────────────────────────────────────────────────────────────
        # 11. SOLD ITEMS
        # ──────────────────────────────────────────────────────────────────────────
        min_sale_id, max_sale_id = get_id_range(conn, "sales", "sale_id")
        sale_span = max(1, max_sale_id - min_sale_id + 1)
        cur_si = get_table_count(conn, "sold_items")
        max_si_id = get_max_id(conn, "sold_items", "sold_item_id")
        if cur_si >= min_rows:
            print(f"[✓] [11/18] SOLD_ITEMS: {cur_si:,d}/{min_rows:,d} rows already present. Skipping.")
        else:
            needed = min_rows - cur_si
            print(f"\n[→] [11/18] SOLD_ITEMS: Resuming at row {cur_si + 1:,d} -> {min_rows:,d} ({needed:,d} remaining)...")
            t0 = time.time()
            copier = FastStreamCopier(
                conn, "sold_items",
                ["sold_item_id", "sale_id", "product_id", "item_name", "size", "quantity",
                 "unit_buy_price", "margin", "unit_sale_price", "total_buy_price", "total_sale_price",
                 "status", "is_return", "return_qty", "is_old", "created_at"],
                batch_size
            )
            for i in range(cur_si + 1, min_rows + 1):
                si_id = max_si_id + (i - cur_si)
                sale_id = min_sale_id + ((i - 1) % sale_span)
                product_id = min_prod_id + ((i - 1) % prod_span)
                dept = DEPARTMENTS[i % len(DEPARTMENTS)]
                cat_items = CATEGORIES_ITEMS.get(dept, ["Sold Article"])
                base_name = cat_items[i % len(cat_items)]
                pad = f" Line-{si_id:07d}"
                item_name = f"{base_name}{pad}"
                size = SIZES[i % len(SIZES)]
                qty = 1.0 + (i % 3)
                unit_buy = round(350.0 + (i % 800), 2)
                margin = round(25.0 + (i % 20), 2)
                unit_sale = round(unit_buy * (1 + margin / 100.0), 2)
                tot_buy = round(unit_buy * qty, 2)
                tot_sale = round(unit_sale * qty, 2)
                is_ret = 1 if i % 40 == 0 else 0
                ret_qty = 1.0 if is_ret else 0.0
                created_at = datetime.datetime(2024, 1, 1) + datetime.timedelta(days=(i % 900))

                copier.add_row([
                    si_id, sale_id, product_id, item_name, size, qty, unit_buy, margin,
                    unit_sale, tot_buy, tot_sale, 0, is_ret, ret_qty, 0, created_at
                ])
                if i % 50000 == 0 or i == min_rows:
                    rate = (i - cur_si) / max(0.01, time.time() - t0)
                    print(f"    --> Sold Items: {i:,d}/{min_rows:,d} ({(i/min_rows)*100:.1f}%) | {rate:,.0f} rows/s")
            copier.flush()

        # ──────────────────────────────────────────────────────────────────────────
        # 12. SOLD ITEM BARCODES
        # ──────────────────────────────────────────────────────────────────────────
        min_si_id, max_si_id = get_id_range(conn, "sold_items", "sold_item_id")
        si_span = max(1, max_si_id - min_si_id + 1)
        cur_sib = get_table_count(conn, "sold_item_barcodes")
        max_sib_id = get_max_id(conn, "sold_item_barcodes", "id")
        if cur_sib >= min_rows:
            print(f"[✓] [12/18] SOLD_ITEM_BARCODES: {cur_sib:,d}/{min_rows:,d} rows already present. Skipping.")
        else:
            needed = min_rows - cur_sib
            print(f"\n[→] [12/18] SOLD_ITEM_BARCODES: Resuming at row {cur_sib + 1:,d} -> {min_rows:,d} ({needed:,d} remaining)...")
            t0 = time.time()
            with conn.cursor() as cur:
                cur.execute("SELECT barcode_no FROM purchase_item WHERE barcode_no > 0 ORDER BY id;")
                valid_barcodes = [r[0] for r in cur.fetchall()]
            b_count = len(valid_barcodes)
            copier = FastStreamCopier(conn, "sold_item_barcodes", ["id", "sold_item_id", "barcode_no"], batch_size)
            for i in range(cur_sib + 1, min_rows + 1):
                sib_id = max_sib_id + (i - cur_sib)
                sold_item_id = min_si_id + ((i - 1) % si_span)
                barcode_no = valid_barcodes[(i - 1) % b_count]
                copier.add_row([sib_id, sold_item_id, barcode_no])
                if i % 50000 == 0 or i == min_rows:
                    rate = (i - cur_sib) / max(0.01, time.time() - t0)
                    print(f"    --> Sold Item Barcodes: {i:,d}/{min_rows:,d} ({(i/min_rows)*100:.1f}%) | {rate:,.0f} rows/s")
            copier.flush()

        # ──────────────────────────────────────────────────────────────────────────
        # 13. SALES PAYMENTS
        # ──────────────────────────────────────────────────────────────────────────
        cur_sp = get_table_count(conn, "sales_payments")
        max_sp_id = get_max_id(conn, "sales_payments", "id")
        if cur_sp >= min_rows:
            print(f"[✓] [13/18] SALES_PAYMENTS: {cur_sp:,d}/{min_rows:,d} rows already present. Skipping.")
        else:
            needed = min_rows - cur_sp
            print(f"\n[→] [13/18] SALES_PAYMENTS: Resuming at row {cur_sp + 1:,d} -> {min_rows:,d} ({needed:,d} remaining)...")
            t0 = time.time()
            copier = FastStreamCopier(
                conn, "sales_payments",
                ["id", "sale_id", "bill_no", "mode_of_payment", "cash", "online", "discount",
                 "total_amount", "paid_amount", "remaining_amount", "final_amount_discount"],
                batch_size
            )
            for i in range(cur_sp + 1, min_rows + 1):
                sp_id = max_sp_id + (i - cur_sp)
                sale_id = min_sale_id + (i - 1)
                bill_no = f"BILL/2024/{sale_id:08d}"
                mode = PAYMENT_MODES[i % len(PAYMENT_MODES)]
                tot = round(1000.0 + (i % 5000), 2)
                disc = round(i % 50, 2)
                final_amt = round(tot - disc, 2)
                cash_amt = round(final_amt * 0.6, 2) if mode == "Cash" else 0.0
                online_amt = final_amt - cash_amt
                copier.add_row([sp_id, sale_id, bill_no, mode, cash_amt, online_amt, disc, tot, final_amt, 0.0, final_amt])
                if i % 50000 == 0 or i == min_rows:
                    rate = (i - cur_sp) / max(0.01, time.time() - t0)
                    print(f"    --> Sales Payments: {i:,d}/{min_rows:,d} ({(i/min_rows)*100:.1f}%) | {rate:,.0f} rows/s")
            copier.flush()

        # ──────────────────────────────────────────────────────────────────────────
        # 14. SALES RETURN ITEMS
        # ──────────────────────────────────────────────────────────────────────────
        cur_sri = get_table_count(conn, "sales_return_items")
        max_sri_id = get_max_id(conn, "sales_return_items", "id")
        if cur_sri >= min_rows:
            print(f"[✓] [14/18] SALES_RETURN_ITEMS: {cur_sri:,d}/{min_rows:,d} rows already present. Skipping.")
        else:
            needed = min_rows - cur_sri
            print(f"\n[→] [14/18] SALES_RETURN_ITEMS: Resuming at row {cur_sri + 1:,d} -> {min_rows:,d} ({needed:,d} remaining)...")
            t0 = time.time()
            copier = FastStreamCopier(
                conn, "sales_return_items",
                ["id", "return_bill_no", "sold_item_id", "customer_name", "customer_no",
                 "item_name", "size", "qty", "sell_price", "sell_total", "reason", "date", "created_at"],
                batch_size
            )
            for i in range(cur_sri + 1, min_rows + 1):
                sri_id = max_sri_id + (i - cur_sri)
                sold_item_id = min_si_id + ((i - 1) % si_span)
                ret_bill = f"RET-SL/{2024 + (i % 2)}/{sri_id:07d}"
                cname = f"{FIRST_NAMES[i % len(FIRST_NAMES)]} {LAST_NAMES[i % len(LAST_NAMES)]}"
                cno = f"9876{i:06d}"[-10:]
                dept = DEPARTMENTS[i % len(DEPARTMENTS)]
                cat_items = CATEGORIES_ITEMS.get(dept, ["Returned Product"])
                item_name = cat_items[i % len(cat_items)]
                size = SIZES[i % len(SIZES)]
                sell_price = round(500.0 + (i % 1000), 2)
                base_reason = RETURN_REASONS[i % len(RETURN_REASONS)]
                pad = generate_payload_chunk(padding_per_row, sri_id)
                reason = f"{base_reason}. {pad}"
                r_date = base_date + datetime.timedelta(days=(i % 900))

                copier.add_row([sri_id, ret_bill, sold_item_id, cname, cno, item_name, size, 1.0, sell_price, sell_price, reason, r_date, r_date])
                if i % 50000 == 0 or i == min_rows:
                    rate = (i - cur_sri) / max(0.01, time.time() - t0)
                    print(f"    --> Sales Return Items: {i:,d}/{min_rows:,d} ({(i/min_rows)*100:.1f}%) | {rate:,.0f} rows/s")
            copier.flush()

        # ──────────────────────────────────────────────────────────────────────────
        # 15. PURCHASE RETURN ITEMS
        # ──────────────────────────────────────────────────────────────────────────
        min_pi_id, max_pi_id = get_id_range(conn, "purchase_item", "id")
        pi_span = max(1, max_pi_id - min_pi_id + 1)
        cur_pri = get_table_count(conn, "purchase_return_items")
        max_pri_id = get_max_id(conn, "purchase_return_items", "id")
        if cur_pri >= min_rows:
            print(f"[✓] [15/18] PURCHASE_RETURN_ITEMS: {cur_pri:,d}/{min_rows:,d} rows already present. Skipping.")
        else:
            needed = min_rows - cur_pri
            print(f"\n[→] [15/18] PURCHASE_RETURN_ITEMS: Resuming at row {cur_pri + 1:,d} -> {min_rows:,d} ({needed:,d} remaining)...")
            t0 = time.time()
            copier = FastStreamCopier(
                conn, "purchase_return_items",
                ["id", "return_bill_no", "purchase_item_id", "product_id", "party", "item_name",
                 "size", "qty", "buy_price", "buy_total", "reason", "date", "invoice_no", "invoice_date", "created_at"],
                batch_size
            )
            for i in range(cur_pri + 1, min_rows + 1):
                pri_id = max_pri_id + (i - cur_pri)
                p_item_id = min_pi_id + ((i - 1) % pi_span)
                prod_id = min_prod_id + ((i - 1) % prod_span)
                ret_bill = f"RET-PR/{2024 + (i % 2)}/{pri_id:07d}"
                party_name = f"Vendor Party #{(min_party_id + ((i - 1) % party_span)):06d}"
                dept = DEPARTMENTS[i % len(DEPARTMENTS)]
                cat_items = CATEGORIES_ITEMS.get(dept, ["Vendor Return Item"])
                item_name = cat_items[i % len(cat_items)]
                size = SIZES[i % len(SIZES)]
                buy_price = round(400.0 + (i % 900), 2)
                base_reason = RETURN_REASONS[i % len(RETURN_REASONS)]
                pad = generate_payload_chunk(padding_per_row, pri_id)
                reason = f"{base_reason}. {pad}"
                r_date = base_date + datetime.timedelta(days=(i % 900))
                inv_no = f"INV/PUR/{pri_id:07d}"

                copier.add_row([
                    pri_id, ret_bill, p_item_id, prod_id, party_name, item_name, size,
                    1.0, buy_price, buy_price, reason, r_date, inv_no, r_date, r_date
                ])
                if i % 50000 == 0 or i == min_rows:
                    rate = (i - cur_pri) / max(0.01, time.time() - t0)
                    print(f"    --> Purchase Return Items: {i:,d}/{min_rows:,d} ({(i/min_rows)*100:.1f}%) | {rate:,.0f} rows/s")
            copier.flush()

        # ──────────────────────────────────────────────────────────────────────────
        # 16. REPLACE BILLS & ITEMS
        # ──────────────────────────────────────────────────────────────────────────
        cur_rep = get_table_count(conn, "replace_bills")
        max_rep_id = get_max_id(conn, "replace_bills", "id")
        max_rep_it_id = get_max_id(conn, "replace_bill_items", "id")
        if cur_rep >= min_rows:
            print(f"[✓] [16/18] REPLACE_BILLS / ITEMS: {cur_rep:,d}/{min_rows:,d} rows already present. Skipping.")
        else:
            needed = min_rows - cur_rep
            print(f"\n[→] [16/18] REPLACE_BILLS: Resuming at row {cur_rep + 1:,d} -> {min_rows:,d} ({needed:,d} remaining)...")
            t0 = time.time()
            copier_rep = FastStreamCopier(
                conn, "replace_bills",
                ["id", "replacebillno", "date", "customername", "customerno", "oldtotal", "newtotal", "difference", "discount", "note"],
                batch_size
            )
            copier_rep_items = FastStreamCopier(
                conn, "replace_bill_items",
                ["id", "replace_bill_id", "side", "item", "size", "qty", "sell_price", "sell_total", "barcode_code", "purchase_item_id"],
                batch_size
            )
            for i in range(cur_rep + 1, min_rows + 1):
                rep_id = max_rep_id + (i - cur_rep)
                rep_item_id = max_rep_it_id + (i - cur_rep)
                p_item_id = min_pi_id + ((i - 1) % pi_span)
                rep_no = f"EXCH/{2024 + (i % 2)}/{rep_id:07d}"
                r_date = base_date + datetime.timedelta(days=(i % 900))
                cname = f"{FIRST_NAMES[i % len(FIRST_NAMES)]} {LAST_NAMES[i % len(LAST_NAMES)]}"
                cno = f"9123{i:06d}"[-10:]
                old_tot = round(600.0 + (i % 400), 2)
                new_tot = round(800.0 + (i % 600), 2)
                diff = round(new_tot - old_tot, 2)
                pad = generate_payload_chunk(padding_per_row, rep_id)
                note = f"Customer exchanged item for alternate size and color. {pad}"

                copier_rep.add_row([rep_id, rep_no, r_date, cname, cno, old_tot, new_tot, diff, 0.0, note])
                copier_rep_items.add_row([
                    rep_item_id, rep_id, "new", "Exchange Replacement Shirt", "L", 1.0, new_tot, new_tot, f"BAR{p_item_id:08d}", p_item_id
                ])
                if i % 50000 == 0 or i == min_rows:
                    rate = (i - cur_rep) / max(0.01, time.time() - t0)
                    print(f"    --> Replace Bills/Items: {i:,d}/{min_rows:,d} ({(i/min_rows)*100:.1f}%) | {rate:,.0f} rows/s")
            copier_rep.flush()
            copier_rep_items.flush()

        # ──────────────────────────────────────────────────────────────────────────
        # 17. STOCK ITEMS & STOCK LEDGER
        # ──────────────────────────────────────────────────────────────────────────
        cur_stk = get_table_count(conn, "stock_items")
        max_stk_id = get_max_id(conn, "stock_items", "id")
        max_stk_led_id = get_max_id(conn, "stock_ledger", "id")
        if cur_stk >= min_rows:
            print(f"[✓] [17/18] STOCK_ITEMS / LEDGER: {cur_stk:,d}/{min_rows:,d} rows already present. Skipping.")
        else:
            needed = min_rows - cur_stk
            print(f"\n[→] [17/18] STOCK_ITEMS: Resuming at row {cur_stk + 1:,d} -> {min_rows:,d} ({needed:,d} remaining)...")
            t0 = time.time()
            copier_stk = FastStreamCopier(
                conn, "stock_items",
                ["id", "name", "group_id", "unit", "opening_stock", "opening_value", "gst_rate", "hsn_code", "is_active", "created_at"],
                batch_size
            )
            copier_stk_led = FastStreamCopier(
                conn, "stock_ledger",
                ["id", "voucher_id", "stock_item_id", "quantity_in", "quantity_out", "rate", "amount", "created_at"],
                batch_size
            )
            for i in range(cur_stk + 1, min_rows + 1):
                stk_it_id = max_stk_id + (i - cur_stk)
                stk_l_id = max_stk_led_id + (i - cur_stk)
                vch_id = min_v_id + ((i - 1) % vch_span)
                stk_name = f"Stock Asset SKU-{stk_it_id:07d}"
                op_stk = float(50 + (i % 100))
                op_val = round(op_stk * 250.0, 2)
                gst = 5.0 if i % 2 == 0 else 12.0
                hsn = f"620{i % 99:02d}"
                c_at = datetime.datetime(2024, 1, 1) + datetime.timedelta(days=(i % 900))
                copier_stk.add_row([stk_it_id, stk_name, 16, "Pcs", op_stk, op_val, gst, hsn, True, c_at])

                qty_in = 10.0 if i % 2 == 0 else 0.0
                qty_out = 5.0 if i % 2 != 0 else 0.0
                rate = 275.0
                copier_stk_led.add_row([stk_l_id, vch_id, stk_it_id, qty_in, qty_out, rate, round((qty_in or qty_out) * rate, 2), c_at])

                if i % 50000 == 0 or i == min_rows:
                    rate = (i - cur_stk) / max(0.01, time.time() - t0)
                    print(f"    --> Stock Ledger: {i:,d}/{min_rows:,d} ({(i/min_rows)*100:.1f}%) | {rate:,.0f} rows/s")
            copier_stk.flush()
            copier_stk_led.flush()

        # ──────────────────────────────────────────────────────────────────────────
        # 18. OLD DATA
        # ──────────────────────────────────────────────────────────────────────────
        cur_old = get_table_count(conn, "old_data")
        max_old_id = get_max_id(conn, "old_data", "id")
        max_uniqee = get_max_id(conn, "old_data", "uniqee_id")
        if cur_old >= min_rows:
            print(f"[✓] [18/18] OLD_DATA: {cur_old:,d}/{min_rows:,d} rows already present. Skipping.")
        else:
            needed = min_rows - cur_old
            print(f"\n[→] [18/18] OLD_DATA: Resuming at row {cur_old + 1:,d} -> {min_rows:,d} ({needed:,d} remaining)...")
            t0 = time.time()
            copier = FastStreamCopier(
                conn, "old_data",
                ["uniqee_id", "id", "item_code", "buy_mrp", "sell_mrp", "remaining", "sold", "imported_at", "is_return"],
                batch_size
            )
            for i in range(cur_old + 1, min_rows + 1):
                o_id = max_old_id + (i - cur_old)
                u_id = max(10000, max_uniqee) + (i - cur_old)
                item_code = f"OLD-SKU-{o_id:07d}"
                buy_mrp = round(200.0 + (i % 600), 2)
                sell_mrp = round(buy_mrp * 1.4, 2)
                rem = float(i % 15)
                sold = float(15 - rem)
                copier.add_row([u_id, o_id, item_code, buy_mrp, sell_mrp, rem, sold, datetime.datetime.now(), 0])
                if i % 50000 == 0 or i == min_rows:
                    rate = (i - cur_old) / max(0.01, time.time() - t0)
                    print(f"    --> Old Data: {i:,d}/{min_rows:,d} ({(i/min_rows)*100:.1f}%) | {rate:,.0f} rows/s")
            copier.flush()

    except KeyboardInterrupt:
        print("\n\n" + "!" * 72)
        print("  [!] Generation paused by user (Ctrl+C / KeyboardInterrupt).")
        print("  [+] All completed batches have been safely committed into PostgreSQL.")
        print("  [+] You can rerun this command at any time to resume exactly where it stopped!")
        print("!" * 72 + "\n")
        print_status(conn)
        conn.close()
        sys.exit(0)

    # ──────────────────────────────────────────────────────────────────────────
    # POST-PROCESSING: Synchronize Serial Sequences & Recompute Caches
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[+] Synchronizing PostgreSQL sequences to prevent ID collisions...")
    seq_tables = [
        ("parties", "party_id"),
        ("customers", "customer_id"),
        ("items", "id"),
        ("purchases_header", "id"),
        ("products", "product_id"),
        ("purchase_item", "id"),
        ("purchase_payments", "id"),
        ("sales", "sale_id"),
        ("sold_items", "sold_item_id"),
        ("sold_item_barcodes", "id"),
        ("sales_payments", "id"),
        ("sales_return_items", "id"),
        ("purchase_return_items", "id"),
        ("replace_bills", "id"),
        ("replace_bill_items", "id"),
        ("vouchers", "id"),
        ("voucher_entries", "id"),
        ("stock_items", "id"),
        ("stock_ledger", "id"),
        ("old_data", "id"),
    ]
    with conn.cursor() as cur:
        for tbl, pk in seq_tables:
            try:
                cur.execute(f"SELECT setval(pg_get_serial_sequence('{tbl}', '{pk}'), COALESCE(MAX({pk}), 1)) FROM {tbl};")
            except Exception as e:
                print(f"    Notice updating sequence for {tbl}: {e}")
        conn.commit()

        # Update last_barcode sentinel in purchase_item
        max_b = get_max_id(conn, "purchase_item", "barcode_no")
        cur.execute(f"UPDATE purchase_item SET last_barcode = {max_b} WHERE barcode_no = 0;")
        conn.commit()

    # Expand existing rows if target GB footprint is not yet satisfied
    with conn.cursor() as cur:
        cur.execute("SELECT pg_database_size(current_database());")
        current_db_bytes = cur.fetchone()[0]

    if (current_db_bytes < (target_gb * (1024 ** 3)) * 0.95 or getattr(args, "expand", False)) and not args.no_padding:
        expand_database_payload(conn, target_gb, batch_size)

    if args.rebuild_cache:
        print("[+] Recomputing dashboard and reporting stats caches...")
        try:
            import core.dashboard_cache as dashboard_cache
            import core.reports_cache as reports_cache
            reports_cache.recompute_all(conn)
            dashboard_cache.recompute_snapshot(conn)
        except Exception as e:
            print(f"    Cache update notice: {e}")

    # Trigger ANALYZE on application tables
    print("[+] Running PostgreSQL ANALYZE on application tables...")
    app_tables = [
        "parties", "customers", "items", "purchases_header", "products",
        "purchase_item", "purchase_payments", "sales", "sold_items",
        "sold_item_barcodes", "sales_payments", "sales_return_items",
        "purchase_return_items", "replace_bills", "replace_bill_items",
        "vouchers", "voucher_entries", "stock_items", "stock_ledger", "old_data"
    ]
    with conn.cursor() as cur:
        for tbl in app_tables:
            try:
                cur.execute(f"ANALYZE {tbl};")
            except Exception:
                pass
        conn.commit()

    total_time = time.time() - start_time
    print_status(conn)
    conn.close()

    print("=" * 72)
    print(f"  SUCCESS! Demo data generation completed in {total_time/60:.2f} minutes.")
    print("=" * 72 + "\n")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Massive Demo Data Generator (500k+ rows per table, 20GB+ footprint, Resumable)"
    )
    parser.add_argument(
        "--rows-per-table", "-r", type=int, default=500000,
        help="Number of rows per table (default: 500,000 / 5 lacs)"
    )
    parser.add_argument(
        "--target-gb", "-g", type=float, default=20.0,
        help="Target database disk footprint in Gigabytes (default: 20.0)"
    )
    parser.add_argument(
        "--batch-size", "-b", type=int, default=50000,
        help="Rows per batch for COPY FROM STDIN streaming (default: 50,000)"
    )
    parser.add_argument(
        "--clean", "-c", action="store_true",
        help="Truncate existing demo data with CASCADE before generating"
    )
    parser.add_argument(
        "--status", "-s", action="store_true",
        help="Display current table row counts and disk sizes without generating"
    )
    parser.add_argument(
        "--no-padding", action="store_true",
        help="Disable text payload padding (generate minimum raw rows only)"
    )
    parser.add_argument(
        "--rebuild-cache", action="store_true",
        help="Rebuild dashboard and report stats caches upon completion"
    )
    parser.add_argument(
        "--expand", action="store_true",
        help="Expand existing rows with high-entropy text payloads to reach target GB footprint immediately"
    )
    # Database connection overrides
    parser.add_argument("--db-url", type=str, default=None, help="PostgreSQL connection string (DATABASE_URL)")
    parser.add_argument("--db-host", type=str, default=None, help="PostgreSQL host (default: localhost)")
    parser.add_argument("--db-port", type=str, default=None, help="PostgreSQL port (default: 5432)")
    parser.add_argument("--db-name", type=str, default=None, help="Database name (default: purchase_tracker)")
    parser.add_argument("--db-user", type=str, default=None, help="Database user (default: postgres)")
    parser.add_argument("--db-password", type=str, default=None, help="Database password (default: Password123)")

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()
    generate_all_demo_data(args)
