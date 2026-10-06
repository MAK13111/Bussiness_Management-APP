"""
Pure-Python database backup / restore.

Why this exists
---------------
The old backup feature shelled out to `pg_dump` / `psql`. Those programs have
to be installed on the machine *and* be the same version family as the server,
which is the most common reason "Download Full Backup" fails after deploying.

This module does the same job using only psycopg2 (already in
requirements.txt) and PostgreSQL's built-in COPY command, so a backup works on
any machine where the app itself can connect to the database.

Backup file format  (a normal .zip)
-----------------------------------
    manifest.json        format name/version, every table + its columns + row
                         count, and the current value of every sequence
    data/<table>.csv     one CSV (with header row) per table

Restore
-------
Runs in ONE transaction: the existing rows are truncated and the backup rows
are loaded. If anything fails, the transaction rolls back and the current
data is left exactly as it was.
"""
import json
import queue
import threading
import zipfile

import psycopg2
import psycopg2.extensions

from core.db import DATABASE_URL, PG_CONFIG

FORMAT_NAME = "erp-backup"
FORMAT_VERSION = 1
_SCHEMA = "public"


# ── helpers ───────────────────────────────────────────────────────────────

def _connect():
    """A dedicated raw psycopg2 connection (not from the app pool)."""
    if DATABASE_URL:
        return psycopg2.connect(DATABASE_URL)
    return psycopg2.connect(**PG_CONFIG)


def _q(cur, name):
    return psycopg2.extensions.quote_ident(name, cur)


def _list_tables(cur):
    cur.execute(
        """
        SELECT c.relname
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relkind IN ('r', 'p') AND NOT c.relispartition
        ORDER BY c.relname
        """,
        (_SCHEMA,),
    )
    return [r[0] for r in cur.fetchall()]


def _columns(cur, table):
    """Insertable columns (generated columns are rebuilt by Postgres itself)."""
    cur.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s AND is_generated = 'NEVER'
        ORDER BY ordinal_position
        """,
        (_SCHEMA, table),
    )
    return [r[0] for r in cur.fetchall()]


def _fk_order(cur, tables):
    """Parents before children. Returns (ordered_tables, has_cycle)."""
    wanted = set(tables)
    cur.execute(
        """
        SELECT child.relname, parent.relname
        FROM pg_constraint con
        JOIN pg_class child  ON child.oid  = con.conrelid
        JOIN pg_class parent ON parent.oid = con.confrelid
        JOIN pg_namespace n  ON n.oid = child.relnamespace
        WHERE con.contype = 'f' AND n.nspname = %s
        """,
        (_SCHEMA,),
    )
    deps = {t: set() for t in tables}
    for child, parent in cur.fetchall():
        if child in wanted and parent in wanted and child != parent:
            deps[child].add(parent)

    ordered, remaining = [], dict(deps)
    while remaining:
        ready = sorted(t for t, d in remaining.items() if not d)
        if not ready:                      # circular foreign keys
            ordered.extend(sorted(remaining))
            return ordered, True
        for t in ready:
            ordered.append(t)
            del remaining[t]
        for d in remaining.values():
            d.difference_update(ready)
    return ordered, False


# ── export ────────────────────────────────────────────────────────────────

def write_backup_zip(fileobj, progress=None):
    """
    Write a complete backup .zip into `fileobj` (a seekable file OR a plain
    write()-only stream). Reads from a single REPEATABLE READ snapshot, so the
    backup is consistent even while the app keeps running.
    """
    conn = _connect()
    try:
        conn.set_session(isolation_level="REPEATABLE READ", readonly=True)
        cur = conn.cursor()
        tables = _list_tables(cur)
        manifest = {
            "format": FORMAT_NAME,
            "format_version": FORMAT_VERSION,
            "created_at": None,
            "tables": {},
            "sequences": {},
        }
        cur.execute("SELECT to_char(now(), 'YYYY-MM-DD\"T\"HH24:MI:SS')")
        manifest["created_at"] = cur.fetchone()[0]

        with zipfile.ZipFile(fileobj, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for t in tables:
                cols = _columns(cur, t)
                if not cols:
                    continue
                col_sql = ", ".join(_q(cur, c) for c in cols)
                sql = "COPY (SELECT {} FROM {}) TO STDOUT WITH (FORMAT csv, HEADER true)".format(
                    col_sql, _q(cur, t)
                )
                with zf.open("data/{}.csv".format(t), "w", force_zip64=True) as out:
                    cur.copy_expert(sql, out)
                manifest["tables"][t] = {"columns": cols, "rows": cur.rowcount}
                if progress:
                    progress(t, cur.rowcount)

            cur.execute(
                "SELECT sequencename, last_value FROM pg_sequences WHERE schemaname = %s",
                (_SCHEMA,),
            )
            for name, last_value in cur.fetchall():
                if last_value is not None:
                    manifest["sequences"][name] = int(last_value)

            zf.writestr("manifest.json", json.dumps(manifest, indent=2))
    finally:
        conn.close()


class _QueueWriter:
    """write()-only file object that hands bytes to a queue (no tell/seek, so
    zipfile switches to streaming mode automatically)."""

    def __init__(self, q):
        self._q = q

    def write(self, data):
        if data:
            self._q.put(bytes(data))
        return len(data)

    def flush(self):
        pass


def stream_backup_zip():
    """
    Generator yielding the backup .zip in chunks while it is being built, so
    the browser download starts immediately and memory stays flat for any
    database size. If the backup fails half-way, the generator raises, so the
    browser reports a FAILED download instead of silently saving a bad file.
    """
    q = queue.Queue(maxsize=64)
    DONE = object()
    err = []

    def worker():
        try:
            write_backup_zip(_QueueWriter(q))
        except BaseException as e:           # noqa: BLE001 - re-raised below
            err.append(e)
        finally:
            q.put(DONE)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    while True:
        item = q.get()
        if item is DONE:
            break
        yield item
    t.join()
    if err:
        raise err[0]


# ── import ────────────────────────────────────────────────────────────────

def is_backup_zip(path):
    return zipfile.is_zipfile(path)


def restore_backup_zip(path, progress=None):
    """
    Replace ALL data in the current database with the contents of a backup
    .zip created by write_backup_zip(). All-or-nothing (single transaction).
    Returns {"tables": n, "rows": n, "skipped_tables": [...]}.
    """
    from core.schema import init_schema, migrate_schema

    with zipfile.ZipFile(path) as zf:
        try:
            manifest = json.loads(zf.read("manifest.json"))
        except KeyError:
            raise ValueError("This zip is not a backup made by this app (manifest.json missing).")
        if manifest.get("format") != FORMAT_NAME:
            raise ValueError("This zip is not a backup made by this app.")
        if manifest.get("format_version", 0) > FORMAT_VERSION:
            raise ValueError("This backup was made by a newer version of the app. Update the app first.")

        # Make sure every table exists (no-op on an already initialised DB).
        init_schema()
        migrate_schema()

        conn = _connect()
        try:
            conn.autocommit = False
            cur = conn.cursor()
            cur.execute("SET LOCAL statement_timeout = 0")
            db_tables = set(_list_tables(cur))

            backup_tables = manifest["tables"]
            to_load = [t for t in backup_tables if t in db_tables]
            skipped = [t for t in backup_tables if t not in db_tables]

            # Every backed-up column must still exist in this database.
            for t in to_load:
                missing = set(backup_tables[t]["columns"]) - set(_columns(cur, t))
                if missing:
                    raise ValueError(
                        "Table '{}' has columns the backup contains but this app version does not: {}. "
                        "Use the same (or a newer) app version than the one that made the backup.".format(
                            t, ", ".join(sorted(missing))
                        )
                    )

            order, has_cycle = _fk_order(cur, to_load)

            # 1) wipe current data (sequences restart; CASCADE handles FKs)
            if to_load:
                cur.execute(
                    "TRUNCATE {} RESTART IDENTITY CASCADE".format(", ".join(_q(cur, t) for t in order))
                )

            # 2) circular FKs can only be loaded with FK triggers off (superuser only)
            if has_cycle:
                cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
                if not cur.fetchone()[0]:
                    raise ValueError("Backup has circular foreign keys and the database user is not a superuser.")
                cur.execute("SET LOCAL session_replication_role = replica")

            # 3) load rows, parents first
            total_rows = 0
            for t in order:
                cols = backup_tables[t]["columns"]
                sql = "COPY {} ({}) FROM STDIN WITH (FORMAT csv, HEADER true)".format(
                    _q(cur, t), ", ".join(_q(cur, c) for c in cols)
                )
                with zf.open("data/{}.csv".format(t)) as src:
                    cur.copy_expert(sql, src)
                total_rows += max(cur.rowcount, 0)
                if progress:
                    progress(t, total_rows)

            # 4) restore sequence counters (barcode counter, ids, ...)
            cur.execute("SELECT sequencename FROM pg_sequences WHERE schemaname = %s", (_SCHEMA,))
            existing_seqs = {r[0] for r in cur.fetchall()}
            for seq, value in manifest.get("sequences", {}).items():
                if seq in existing_seqs:
                    cur.execute("SELECT setval(%s, %s, true)", ('{}.{}'.format(_SCHEMA, _q(cur, seq)), value))

            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    # Re-apply any seed rows / newer columns the old backup didn't have.
    migrate_schema()
    return {"tables": len(order), "rows": total_rows, "skipped_tables": skipped}