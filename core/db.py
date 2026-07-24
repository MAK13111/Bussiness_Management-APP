import os
import sqlite3
from contextlib import contextmanager

# ─── DATABASE ──────────────────────────────────────────────────────────
DB_DIR = "DATABASE"
os.makedirs(DB_DIR, exist_ok=True)
MAIN_DB = os.path.join(DB_DIR, "purchase_tracker.db")

@contextmanager
def get_conn():
    conn = sqlite3.connect(MAIN_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    # Without this, SQLite silently ignores every "ON DELETE CASCADE" in the
    # schema, leaving orphaned voucher_entries/stock_ledger rows behind
    # whenever a parent row (e.g. a voucher) is deleted.
    conn.execute("PRAGMA foreign_keys=ON")
    # Below pragmas matter once the DB file grows into the GB range -- the
    # defaults (tiny page cache, disk-based temp tables) cause heavy disk
    # I/O on a large file. None of these change query results.
    conn.execute("PRAGMA synchronous=NORMAL")   # safe with WAL, much faster commits
    conn.execute("PRAGMA cache_size=-64000")    # ~64MB page cache instead of default ~2MB
    conn.execute("PRAGMA temp_store=MEMORY")    # temp sorts/joins in RAM, not disk
    conn.execute("PRAGMA mmap_size=268435456")  # memory-map up to 256MB of the file for faster reads
    conn.execute("PRAGMA busy_timeout=5000")    # avoid "database is locked" under concurrent writes
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def _add_column_if_missing(conn, table_name, column_name, column_type):
    existing = [row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()]
    if column_name not in existing:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
