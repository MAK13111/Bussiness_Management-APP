# SQLite → PostgreSQL migration notes

## Files changed
- **core/db.py** — rewritten. Connects to Postgres via `psycopg2` instead of
  `sqlite3`. Includes a compatibility layer so `conn.execute("... ? ...", params)`
  still works everywhere (translates `?` → `%s`, emulates `cursor.lastrowid`
  via `RETURNING id`, converts `INSERT OR IGNORE` → `ON CONFLICT DO NOTHING`).
  Also registers typecasters so `NUMERIC` columns come back as `float` (not
  `Decimal`) and `DATE`/`TIMESTAMP` columns come back as strings — matching
  what your code already expects from the old sqlite REAL/TEXT columns.
- **core/schema.py** — rewritten to just execute `core/schema.sql` (your
  Postgres DDL) instead of hand-written `CREATE TABLE` calls. It's idempotent,
  so calling it on every startup is still safe.
- **core/schema.sql** — your `db_structpost.txt`, with only the
  `CREATE DATABASE erp_db;` line removed (the app connects to an
  already-created database — see "What you still need to do" below).
- **core/accounting.py** — same logic, but with the Postgres-specific fixes
  it actually needs (see below). Nothing about *what* it calculates changed.
- **core/shared_helpers.py** — one line: `1` → `True` for the `is_active`
  boolean parameter.
- **auth.py, calculations.py** — unchanged (no SQL in either file).

## Why accounting.py needed more than a find-and-replace
A few things in the original SQL were SQLite-specific and would have failed
silently or loudly on Postgres — these aren't functional changes, just
making the same logic actually run on Postgres:

1. **`HAVING balance > 0`** — SQLite lets you reference a `SELECT`-list alias
   in `HAVING`; Postgres doesn't. Replaced with the full expression
   (`HAVING COALESCE(SUM(...) - SUM(...), 0) > 0`) in both places in
   `get_profit_loss()`.
2. **`MAX(a, b)`** — in SQLite this is the *scalar* "greatest of two values"
   function. In Postgres, `MAX` is aggregate-only and doesn't accept two
   arguments. Changed to `GREATEST(a, b)` in `get_day_book()`.
3. **`date(v.date) = date(?)`** — was needed in SQLite because dates were
   stored as `TEXT`. Postgres's `date` column is a real `DATE` type, so the
   string parameter compares directly; simplified to `v.date = ?`.
4. **Retry loop on voucher-number collisions** — in SQLite, a failed INSERT
   doesn't affect the rest of the transaction, so the old code could just
   retry on the same connection. In Postgres, one failed statement aborts
   the whole transaction until it's rolled back. Each retry attempt now
   runs inside its own `SAVEPOINT` (`conn.savepoint()` /
   `conn.rollback_to_savepoint()`), and the code now catches
   `psycopg2.errors.UniqueViolation` instead of `sqlite3.IntegrityError`.
5. **Boolean literals** — `is_posted`/`is_active` are now real `BOOLEAN`
   columns instead of `INTEGER 0/1`. Postgres won't silently cast an int
   parameter to boolean, so those call sites now pass `True`.

## What you still need to do
1. **Install the driver**: `pip install psycopg2-binary`
2. **Create the database once** (the app no longer does this for you):
   ```
   createdb erp_db
   ```
   (or `CREATE DATABASE erp_db;` from `psql` with a superuser role)
3. **Set connection info** via environment variable, either:
   - `DATABASE_URL=postgresql://user:password@host:5432/erp_db`, or
   - `PGHOST` / `PGPORT` / `PGDATABASE` / `PGUSER` / `PGPASSWORD`
4. **Run schema init once** (same as before): call `schema.init_schema()`
   on startup, same as your app already does — it now just runs
   `core/schema.sql` instead of the old Python `CREATE TABLE` calls.
5. **Migrate existing data** from `purchase_tracker.db` if you need to keep
   your current records — this pass only migrated the *code*, not the data.
   A tool like `pgloader` can move a SQLite file straight into Postgres
   using `core/schema.sql`'s table shapes as the target. Happy to help set
   that up if you want it.

## One thing to keep an eye on
Anywhere your **routes** (not included in what you uploaded) do their own
raw SQL with `?` placeholders or read `row['some_date_column']` expecting a
string — they should keep working unchanged thanks to the compatibility
layer in `db.py`. But if any route does its own `import sqlite3` error
handling (like the old voucher retry loop did) or relies on SQLite-only
functions (`date()`, multi-arg `MAX()`, etc.), those will need the same
kind of fix shown above. If you share `routes/*.py`, I can check them the
same way.
