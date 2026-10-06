import os
import re
import threading
from contextlib import contextmanager

import psycopg2
import psycopg2.errors
import psycopg2.extensions
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool
import core.env
# ─── DATABASE ──────────────────────────────────────────────────────────
# Was a local SQLite file (DATABASE/purchase_tracker.db). Now PostgreSQL.
#
# Point this at your Postgres instance with a single DATABASE_URL env var
# (e.g. postgresql://user:password@host:5432/erp_db), or fall back to the
# individual PG* vars (same names psql/libpq already understand) if that's
# not set -- whichever is easier for your hosting setup.
DATABASE_URL = os.environ.get("DATABASE_URL")

PG_CONFIG = dict(
    host=os.environ.get("PGHOST", "localhost"),
    port=os.environ.get("PGPORT", "5432"),
    dbname=os.environ.get("PGDATABASE", "purchase_tracker"),
    user=os.environ.get("PGUSER", "postgres"),
    password=os.environ.get("PGPASSWORD", ""),  # set PGPASSWORD (or DATABASE_URL) in .env
)

_pool = None
# Lock that ensures pool creation is safe when Waitress spins up many
# worker threads simultaneously (prevents a race that creates two pools).
_pool_lock = threading.Lock()


def _get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            # Double-checked locking: another thread may have finished
            # pool init while we were waiting for the lock.
            if _pool is None:
                if DATABASE_URL:
                    _pool = ThreadedConnectionPool(2, 20, DATABASE_URL, **_KEEPALIVE)
                else:
                    _pool = ThreadedConnectionPool(2, 20, **PG_CONFIG, **_KEEPALIVE)
    return _pool

# TCP keepalives so firewalls / Windows / routers don't silently drop idle connections.
_KEEPALIVE = dict(keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5)


def reset_pool():
    """Close every pooled connection so the next request opens fresh ones.

    Call after anything that kills all sessions (database drop / restore)."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.closeall()
            except Exception:
                pass
            _pool = None


# psycopg2 returns NUMERIC/DECIMAL columns as Decimal by default. Every
# calculation in this app (calculations.py, accounting.py) was written
# assuming plain floats (matching sqlite's REAL columns), and Decimal
# doesn't mix with float in arithmetic (`Decimal('1') + 1.5` raises
# TypeError). Registering this globally keeps every existing formula
# working unchanged instead of having to sprinkle float(...) everywhere.
_DEC2FLOAT = psycopg2.extensions.new_type(
    psycopg2.extensions.DECIMAL.values,
    "DEC2FLOAT",
    lambda value, curs: float(value) if value is not None else None,
)
psycopg2.extensions.register_type(_DEC2FLOAT)

# Same reasoning for DATE/TIMESTAMP: the old sqlite schema stored these as
# TEXT, so the rest of the app (JSON responses, string comparisons, etc.)
# expects plain strings, not date/datetime objects. Postgres returns real
# date/timestamp objects by default -- cast them back to strings here so
# nothing downstream needs to change (and so jsonify() doesn't choke on a
# raw date object, which it isn't set up to serialize).
def _date_to_str(value, curs):
    # `value` here is the raw text Postgres sent for this column (e.g.
    # "2026-08-01"), not a parsed date object -- that's what makes this a
    # *caster*. It's already in the format the rest of the app expects.
    return value


def _ts_to_str(value, curs):
    if value is None:
        return None
    # Postgres's default text form is "YYYY-MM-DD HH:MM:SS[.ffffff]" --
    # strip any fractional-seconds part to match the old sqlite TEXT format.
    return value.split(".")[0]


_DATE_OID = 1082
_TIMESTAMP_OID = 1114
_DATE_AS_STR = psycopg2.extensions.new_type((_DATE_OID,), "DATE_AS_STR", _date_to_str)
_TIMESTAMP_AS_STR = psycopg2.extensions.new_type((_TIMESTAMP_OID,), "TIMESTAMP_AS_STR", _ts_to_str)
psycopg2.extensions.register_type(_DATE_AS_STR)
psycopg2.extensions.register_type(_TIMESTAMP_AS_STR)


# ─── SQLITE-STYLE COMPATIBILITY LAYER ──────────────────────────────────
# accounting.py / shared_helpers.py (and anything else in the codebase)
# were written against sqlite3's API: conn.execute(sql_with_question_marks,
# params) returning a cursor with .fetchone()/.fetchall()/.lastrowid, and
# rows that support row['col'] access. The wrapper below reproduces that
# exact surface on top of psycopg2 so none of those call sites need to
# change -- only this file (and the DB-specific quirks below) had to.

_PLACEHOLDER_RE = re.compile(r"\?")
_INSERT_RE = re.compile(r"^\s*INSERT\s+(?:OR\s+IGNORE\s+)?INTO\s+(\w+)", re.IGNORECASE)
_INSERT_OR_IGNORE_RE = re.compile(r"INSERT\s+OR\s+IGNORE\s+INTO", re.IGNORECASE)
_RETURNING_RE = re.compile(r"\bRETURNING\b", re.IGNORECASE)

# Tables whose primary key is not the column named "id".
_TABLE_PK = {
    "parties": "party_id",
    "products": "product_id",
    "customers": "customer_id",
    "sales": "sale_id",
    "sold_items": "sold_item_id",
}


def _qmark_to_pyformat(sql):
    """
    Translate sqlite '?' placeholders to psycopg2 '%s' placeholders.
    Any literal '%' already in the query (e.g. LIKE '...%') has to be
    escaped to '%%' first, or psycopg2 tries to treat it as a format spec
    and blows up with "not enough arguments for format string".
    """
    sql = sql.replace("%", "%%")
    return _PLACEHOLDER_RE.sub("%s", sql)


class _Cursor:
    """Wraps a psycopg2 RealDictCursor to add sqlite3-style lastrowid + INSERT OR IGNORE support."""

    def __init__(self, cur):
        self._cur = cur
        self.lastrowid = None

    def execute(self, sql, params=None):
        params = params or ()
        original_sql = sql

        if _INSERT_OR_IGNORE_RE.search(sql):
            # sqlite: INSERT OR IGNORE INTO ...  ->  postgres: INSERT INTO ... ON CONFLICT DO NOTHING
            sql = _INSERT_OR_IGNORE_RE.sub("INSERT INTO", sql)
            sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"

        sql = _qmark_to_pyformat(sql)

        insert_match = _INSERT_RE.match(original_sql)
        is_insert = insert_match is not None
        needs_returning = is_insert and not _RETURNING_RE.search(sql)
        pk_col = "id"
        if needs_returning:
            # Postgres has no cursor.lastrowid -- emulate it with RETURNING <pk>.
            table = insert_match.group(1).lower()
            pk_col = _TABLE_PK.get(table, "id")
            sql = sql.rstrip().rstrip(";") + f" RETURNING {pk_col}"

        self._cur.execute(sql, params)

        self.lastrowid = None
        if needs_returning:
            try:
                row = self._cur.fetchone()
                if row:
                    if isinstance(row, dict):
                        self.lastrowid = row.get(pk_col) or row.get("id") or next(iter(row.values()), None)
                    else:
                        self.lastrowid = row[0]
            except (psycopg2.ProgrammingError, IndexError, KeyError):
                # e.g. ON CONFLICT DO NOTHING inserted nothing -> no row to return
                pass
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def fetchmany(self, size=None):
        return self._cur.fetchmany(size) if size is not None else self._cur.fetchmany()

    def executemany(self, sql, params_seq):
        sql = _qmark_to_pyformat(sql)
        self._cur.executemany(sql, params_seq)
        return self

    def __getattr__(self, name):
        return getattr(self._cur, name)


class _Connection:
    """Wraps a psycopg2 connection so it keeps supporting conn.execute(...) like sqlite3 did.

    Root-cause fix for "connection already closed" under Waitress
    ------------------------------------------------------------
    The original implementation created ONE shared _Cursor (_wrapped_cursor)
    in __init__ and reused it for every conn.execute() call. Under a
    multi-threaded WSGI server this caused two failure modes:

    1. If any statement raised an exception, psycopg2 marks the cursor (and
       the whole transaction) as aborted. The next conn.execute() on that
       same shared cursor raises "InterfaceError: connection already closed"
       before get_conn()'s finally block can even call rollback/putconn.

    2. Code that mixes conn.cursor() (raw psycopg2) with conn.execute()
       (shared compat cursor) on the same connection -- e.g. migrate_schema
       calling cur.execute(savepoint) interleaved with conn.execute() --
       produced interleaved cursor state that triggered the same error.

    Fix: every execute() / executemany() / savepoint helper opens its own
    brand-new cursor. Cursors are cheap psycopg2 client-side objects;
    creating one per statement has no measurable overhead per web request.
    """

    def __init__(self, pg_conn):
        self._conn = pg_conn

    def _new_cursor(self):
        """Open a fresh RealDictCursor wrapped in the sqlite3-compat _Cursor."""
        raw = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        return _Cursor(raw)

    def execute(self, sql, params=None):
        # Always use a fresh cursor so that any previously aborted statement
        # cannot poison subsequent execute() calls on this connection.
        return self._new_cursor().execute(sql, params)

    def cursor(self):
        """Raw psycopg2 cursor (dict rows), for callers that want it directly (e.g. schema.py)."""
        return self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    # --- Savepoint helpers ---------------------------------------------
    # Unlike sqlite, a failed statement in Postgres poisons the entire
    # transaction until it's rolled back -- you can't just retry on the
    # same connection. Anywhere the old code retried an INSERT after a
    # collision (see accounting.py's voucher-number retry loop) now needs
    # to wrap each attempt in a SAVEPOINT so only that attempt gets undone.
    def savepoint(self, name):
        # Dedicated fresh cursor so savepoint commands never share state
        # with a data cursor from a previous execute() call.
        self._new_cursor().execute(f"SAVEPOINT {name}")

    def rollback_to_savepoint(self, name):
        self._new_cursor().execute(f"ROLLBACK TO SAVEPOINT {name}")

    def release_savepoint(self, name):
        self._new_cursor().execute(f"RELEASE SAVEPOINT {name}")

    def executemany(self, sql, params_seq):
        """Batch execution compatible with SQLite's conn.executemany() call style."""
        cur = self._new_cursor()
        cur.executemany(sql, params_seq)
        return self


@contextmanager
def get_conn():
    pool = _get_pool()

    # Borrow a connection and validate it is still alive on the server.
    # psycopg2 pools recycle connections silently. When Postgres drops an
    # idle connection (tcp keepalive timeout, pg_terminate_backend, server
    # restart, idle_in_transaction_session_timeout, etc.) the psycopg2
    # client-side object still has closed=0 because it hasn't tried the
    # socket yet -- it only discovers the drop on the first actual use,
    # producing "OperationalError: server closed the connection unexpectedly".
    #
    # Fix: after borrowing from the pool, call pg_conn.reset() which does a
    # cheap ROLLBACK/sync round-trip. If the server dropped the connection,
    # reset() raises OperationalError immediately -- we catch it, evict the
    # dead connection from the pool, and borrow a brand-new one instead.
    # We retry at most once; if the second attempt also fails, the database
    # is genuinely unreachable and we let the error propagate.
    pg_conn = None
    for _attempt in range(6):
        pg_conn = pool.getconn()

        # Client-side check: psycopg2 sets closed != 0 when it already knows
        # the connection is gone (e.g. prior explicit close or error path).
        if pg_conn.closed:
            try:
                pool.putconn(pg_conn, close=True)
            except Exception:
                pass
            pg_conn = None
            continue  # retry with a fresh connection

        try:
            # reset() rolls back any stale open transaction and verifies the
            # server round-trip, making it the cheapest liveness probe.
            pg_conn.reset()
            break  # connection is healthy
        except psycopg2.OperationalError:
            # Server dropped this connection since it was last used.
            # Evict it from the pool so no other thread borrows it.
            try:
                pool.putconn(pg_conn, close=True)
            except Exception:
                pass
            pg_conn = None
            # If this was the last attempt, give up and let it raise on
            # the next getconn() below (or re-raise on the second loop).

    if pg_conn is None or pg_conn.closed:
        # Both attempts failed -- database is unreachable.
        raise psycopg2.OperationalError(
            "Could not obtain a live database connection after 6 attempts."
        )

    conn = _Connection(pg_conn)
    try:
        # Reset session-level timeouts on every borrow.
        # psycopg2 pools reuse connections, so SET commands from a previous
        # borrow (e.g. migrate_schema sets statement_timeout='30s') persist
        # into the next request and can cancel long-running queries like
        # dashboard cache recomputes.
        #   statement_timeout = 0  -> no limit (default postgres behaviour)
        #   idle_in_transaction_session_timeout = 60s -> auto-kill zombie
        #     connections that hold table locks without doing any work.
        conn.execute("SET statement_timeout = 0")
        conn.execute("SET idle_in_transaction_session_timeout = '60s'")
        yield conn
        conn.commit()
    except Exception:
        # Roll back on any error. If the connection itself is broken the
        # rollback call will raise -- catch it silently so the original
        # caller exception is the one that propagates.
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        # If the psycopg2 connection broke during the request, remove it
        # from the pool instead of recycling a dead socket.
        broken = pg_conn.closed != 0
        try:
            pool.putconn(pg_conn, close=broken)
        except Exception:
            pass


def ensure_database_exists():
    """
    Connects to Postgres's 'postgres' maintenance database and creates the
    app's target database if it doesn't exist yet.

    Returns True if the database was just created (first run), or False if
    it already existed. Callers use this to skip schema init entirely when
    the database already existed, instead of re-running it every startup.
    """
    if DATABASE_URL:
        conn_params = psycopg2.extensions.parse_dsn(DATABASE_URL)
    else:
        conn_params = dict(PG_CONFIG)

    target_db = conn_params["dbname"]
    maint_params = dict(conn_params)
    maint_params["dbname"] = "postgres"

    maint_conn = psycopg2.connect(**maint_params)
    maint_conn.autocommit = True  # CREATE DATABASE can't run inside a transaction block
    try:
        cur = maint_conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
        if cur.fetchone() is not None:
            return False  # already exists -- skip creation entirely

        # Database identifiers can't be parameterized -- quote it safely instead.
        cur.execute('CREATE DATABASE "{}"'.format(target_db.replace('"', '""')))
        return True
    finally:
        maint_conn.close()


def _add_column_if_missing(conn, table_name, column_name, column_type):
    # Postgres supports "ADD COLUMN IF NOT EXISTS" natively, so (unlike the
    # old sqlite version) there's no need to query the columns list first.
    conn.execute(
        f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_name} {column_type}"
    )
