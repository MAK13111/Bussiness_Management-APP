
"""
generate_bulk_test_data.py

Bulk-data generator for purchase_tracker.db.

IMPORTANT:
- Adds NEW data without repeating existing identifiers.
- Existing database rows are preserved unless --wipe is used.
- Invoice numbers, bill numbers, barcode codes, return bill numbers,
  party names and GST numbers are generated uniquely against existing DB data.
- Foreign-key-style references are kept valid.
- Pure Python standard library only.

Usage:
    python generate_bulk_test_data.py
    python generate_bulk_test_data.py --total 500000
    python generate_bulk_test_data.py --seed 123
    python generate_bulk_test_data.py --wipe
"""

import argparse
import os
import random
import sqlite3
import string
import time
from datetime import datetime, timedelta


# ============================================================
# CONFIG
# ============================================================

DEFAULT_COUNTS = {
    "departments":      10,
    "parties":          500,
    "products":         2_000,
    "items":            2_000,
    "purchases":        35_000,
    "purchase_items":   175_000,
    "purchase_borrow":  6_000,
    "barcodes":         8_000,
    "sales":            55_000,
    "sale_items":       205_000,
    "sales_borrow":     6_000,
    "payments":         3_000,
    "purchase_returns": 1_500,
    "sales_returns":    1_500,
}

BATCH_SIZE = 5_000

DATE_START = datetime(2023, 1, 1)
DATE_END = datetime(2026, 7, 22)


# ============================================================
# VOCABULARY
# ============================================================

DEPT_NAMES = [
    "Menswear",
    "Womenswear",
    "Kids",
    "Footwear",
    "Accessories",
    "Electronics",
    "Groceries",
    "Stationery",
    "Home & Kitchen",
    "Sports",
]

FIRST_NAMES = [
    "Amit", "Priya", "Rahul", "Sneha", "Vikram",
    "Anita", "Rohan", "Kavya", "Suresh", "Divya",
    "Arjun", "Neha", "Manoj", "Pooja", "Karthik",
    "Meera", "Sanjay", "Ritu", "Deepak", "Anjali",
]

LAST_NAMES = [
    "Sharma", "Verma", "Patel", "Iyer", "Reddy",
    "Nair", "Gupta", "Singh", "Rao", "Mehta",
    "Joshi", "Kulkarni", "Das", "Chauhan",
]

COMPANY_SUFFIX = [
    "Traders",
    "Enterprises",
    "Textiles",
    "Distributors",
    "Wholesale",
    "Impex",
    "Retail Co",
    "& Sons",
    "Fashions",
    "Stores",
]

CITIES = [
    "Pune",
    "Mumbai",
    "Delhi",
    "Bangalore",
    "Chennai",
    "Hyderabad",
    "Kolkata",
    "Ahmedabad",
    "Nagpur",
    "Surat",
]

ITEM_ADJ = [
    "Cotton",
    "Slim Fit",
    "Regular Fit",
    "Premium",
    "Classic",
    "Casual",
    "Formal",
    "Printed",
    "Plain",
    "Denim",
]

ITEM_NOUN = [
    "Shirt",
    "T-Shirt",
    "Trouser",
    "Jeans",
    "Jacket",
    "Kurta",
    "Saree",
    "Shoes",
    "Sandals",
    "Cap",
    "Belt",
    "Wallet",
]

SIZES = [
    "S", "M", "L", "XL", "XXL",
    "28", "30", "32", "34", "Free Size",
]

UNITS = [
    "pcs",
    "pair",
    "box",
    "set",
]

PAYMENT_MODES = [
    "Cash",
    "UPI",
    "Bank",
    "Card",
    "Other",
]

STATUSES = [
    "Pending",
    "Partial",
    "Paid",
]


# ============================================================
# SCHEMA
# ============================================================

SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS departments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )""",

    """CREATE TABLE IF NOT EXISTS parties (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        seller_no TEXT,
        address TEXT,
        gst_no TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""",

    """CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        department TEXT,
        hsn TEXT,
        unit TEXT,
        default_margin REAL DEFAULT 0,
        default_gst REAL DEFAULT 0,
        min_stock REAL DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""",

    """CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        department TEXT,
        hsn TEXT,
        unit TEXT,
        defaultMargin REAL DEFAULT 0,
        defaultGST REAL DEFAULT 0,
        min_stock REAL DEFAULT 0,
        createdAt TEXT,
        size TEXT
    )""",

    """CREATE TABLE IF NOT EXISTS purchases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_no TEXT,
        party TEXT,
        seller_no TEXT,
        seller_address TEXT,
        seller_gst_no TEXT,
        date TEXT NOT NULL,
        department TEXT,
        mode TEXT NOT NULL CHECK (mode IN ('cash','credit')),
        total_buy REAL DEFAULT 0,
        total_sell REAL DEFAULT 0,
        total_with_gst REAL DEFAULT 0,
        cgst_rate REAL DEFAULT 0,
        sgst_rate REAL DEFAULT 0,
        igst_rate REAL DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        voucher_id INTEGER,
        discount REAL DEFAULT 0
    )""",

    """CREATE TABLE IF NOT EXISTS purchase_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        purchase_id INTEGER NOT NULL,
        product_id INTEGER,
        item TEXT NOT NULL,
        size TEXT,
        qty REAL NOT NULL,
        sold REAL DEFAULT 0,
        buy_price REAL NOT NULL,
        margin REAL DEFAULT 0,
        sell_price REAL DEFAULT 0,
        buy_total REAL DEFAULT 0,
        sell_total REAL DEFAULT 0,
        profit REAL DEFAULT 0,
        cgst REAL DEFAULT 0,
        sgst REAL DEFAULT 0,
        igst REAL DEFAULT 0,
        total_with_gst REAL DEFAULT 0,
        department TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        original_buy_price REAL
    )""",

    """CREATE TABLE IF NOT EXISTS purchase_borrow (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        purchase_id INTEGER NOT NULL,
        invoice_no TEXT,
        party_name TEXT,
        party_phone TEXT,
        total_amount REAL NOT NULL,
        paid_amount REAL DEFAULT 0,
        balance_amount REAL DEFAULT 0,
        due_date TEXT,
        status TEXT DEFAULT 'Pending'
            CHECK (status IN ('Pending','Partial','Paid')),
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""",

    """CREATE TABLE IF NOT EXISTS barcodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        purchase_item_id INTEGER,
        product_name TEXT,
        size TEXT,
        party TEXT,
        sell_price REAL,
        buy_price REAL,
        margin REAL,
        status TEXT DEFAULT 'available'
            CHECK (status IN ('available','sold')),
        created_at TEXT,
        sold_at TEXT
    )""",

    """CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bill_no TEXT,
        customer_name TEXT,
        customer_no TEXT,
        date TEXT NOT NULL,
        mode TEXT NOT NULL CHECK (mode IN ('cash','credit')),
        payment_mode TEXT,
        total_sell REAL DEFAULT 0,
        total_buy REAL DEFAULT 0,
        total_profit REAL DEFAULT 0,
        discount REAL DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        voucher_id INTEGER
    )""",

    """CREATE TABLE IF NOT EXISTS sale_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER NOT NULL,
        product_id INTEGER,
        item TEXT NOT NULL,
        size TEXT,
        qty REAL NOT NULL,
        buy_price REAL DEFAULT 0,
        margin REAL DEFAULT 0,
        sell_price REAL DEFAULT 0,
        buy_total REAL DEFAULT 0,
        sell_total REAL DEFAULT 0,
        profit REAL DEFAULT 0,
        discount REAL DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        purchase_item_id INTEGER,
        barcode_code TEXT
    )""",

    """CREATE TABLE IF NOT EXISTS sales_borrow (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER NOT NULL,
        bill_no TEXT,
        customer_name TEXT,
        customer_phone TEXT,
        total_amount REAL NOT NULL,
        received_amount REAL DEFAULT 0,
        balance_amount REAL DEFAULT 0,
        due_date TEXT,
        status TEXT DEFAULT 'Pending'
            CHECK (status IN ('Pending','Partial','Paid')),
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""",

    """CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        borrow_type TEXT NOT NULL CHECK (borrow_type IN ('purchase','sales')),
        borrow_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        payment_date TEXT NOT NULL,
        payment_mode TEXT
            CHECK (payment_mode IN ('Cash','UPI','Bank','Card','Other')),
        reference_no TEXT,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""",

    """CREATE TABLE IF NOT EXISTS purchase_returns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        returnBillNo TEXT,
        date TEXT,
        party TEXT,
        item TEXT,
        size TEXT,
        qty REAL,
        buy REAL,
        buyTotal REAL,
        baseCode TEXT,
        originalInvoiceNo TEXT,
        originalTable TEXT,
        originalId INTEGER,
        reason TEXT,
        department TEXT
    )""",

    """CREATE TABLE IF NOT EXISTS sales_returns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        returnBillNo TEXT,
        date TEXT,
        customerName TEXT,
        customerNo TEXT,
        item TEXT,
        size TEXT,
        qty REAL,
        sellUnit REAL,
        sellTotal REAL,
        baseCode TEXT,
        originalBillNo TEXT,
        originalTable TEXT,
        originalId INTEGER,
        reason TEXT
    )""",
]


INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS idx_purchases_date ON purchases(date)",
    "CREATE INDEX IF NOT EXISTS idx_purchases_mode ON purchases(mode)",
    "CREATE INDEX IF NOT EXISTS idx_purchase_items_pid ON purchase_items(purchase_id)",
    "CREATE INDEX IF NOT EXISTS idx_purchase_items_item ON purchase_items(item)",
    "CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(date)",
    "CREATE INDEX IF NOT EXISTS idx_sales_mode ON sales(mode)",
    "CREATE INDEX IF NOT EXISTS idx_sale_items_sid ON sale_items(sale_id)",
    "CREATE INDEX IF NOT EXISTS idx_sale_items_item ON sale_items(item)",
    "CREATE INDEX IF NOT EXISTS idx_barcodes_status ON barcodes(status)",
    "CREATE INDEX IF NOT EXISTS idx_purchase_returns_date ON purchase_returns(date)",
    "CREATE INDEX IF NOT EXISTS idx_sales_returns_date ON sales_returns(date)",
    "CREATE INDEX IF NOT EXISTS idx_items_name_size ON items(name, size)",
    "CREATE INDEX IF NOT EXISTS idx_purchase_items_item_size ON purchase_items(item, size)",
    "CREATE INDEX IF NOT EXISTS idx_parties_name ON parties(name)",
]


TABLES_IN_DEPENDENCY_ORDER = [
    "sales_returns",
    "purchase_returns",
    "payments",
    "sales_borrow",
    "sale_items",
    "sales",
    "barcodes",
    "purchase_borrow",
    "purchase_items",
    "purchases",
    "items",
    "products",
    "parties",
    "departments",
]


# ============================================================
# DATABASE
# ============================================================

def connect(db_path):
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA foreign_keys=OFF")

    return conn


def ensure_schema(conn):
    for stmt in SCHEMA_STATEMENTS:
        conn.execute(stmt)

    for stmt in INDEX_STATEMENTS:
        conn.execute(stmt)

    conn.commit()


def wipe(conn):
    print("Wiping existing rows...")

    for table in TABLES_IN_DEPENDENCY_ORDER:
        conn.execute(f"DELETE FROM {table}")

    conn.execute(
        "DELETE FROM sqlite_sequence WHERE name IN ({})".format(
            ",".join("?" for _ in TABLES_IN_DEPENDENCY_ORDER)
        ),
        TABLES_IN_DEPENDENCY_ORDER,
    )

    conn.commit()


def max_id(conn, table):
    row = conn.execute(
        f"SELECT COALESCE(MAX(id), 0) AS m FROM {table}"
    ).fetchone()

    return row["m"]


# ============================================================
# UNIQUE DATA HELPERS
# ============================================================

def existing_values(conn, table, column):
    """
    Loads existing values from the database so newly generated
    data can never duplicate them.
    """

    try:
        rows = conn.execute(
            f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL"
        ).fetchall()

        return {
            str(row[column])
            for row in rows
            if row[column] is not None
        }

    except sqlite3.OperationalError:
        return set()


def unique_value(generator, used):
    """
    Keeps generating until a value not already present
    in the database is found.
    """

    while True:
        value = generator()

        if value not in used:
            used.add(value)
            return value


def make_unique_invoice(used, start_number):
    """
    Generates unique purchase invoice numbers.
    """

    counter = start_number

    while True:
        value = f"PINV{counter}"

        if value not in used:
            used.add(value)
            return value

        counter += 1


def make_unique_bill(used, start_number):
    """
    Generates unique sales bill numbers.
    """

    counter = start_number

    while True:
        value = f"SINV{counter}"

        if value not in used:
            used.add(value)
            return value

        counter += 1


def make_unique_barcode(used, start_number):
    """
    Generates unique barcode codes.
    """

    counter = start_number

    while True:
        value = f"BC{counter}"

        if value not in used:
            used.add(value)
            return value

        counter += 1


def make_unique_purchase_return(used, start_number):
    counter = start_number

    while True:
        value = f"PRET{counter:08d}"

        if value not in used:
            used.add(value)
            return value

        counter += 1


def make_unique_sales_return(used, start_number):
    counter = start_number

    while True:
        value = f"SRET{counter:08d}"

        if value not in used:
            used.add(value)
            return value

        counter += 1


# ============================================================
# RANDOM HELPERS
# ============================================================

def rand_gst_no():
    return (
        f"{random.randint(1, 37):02d}"
        f"{''.join(random.choices(string.ascii_uppercase, k=5))}"
        f"{''.join(random.choices(string.digits, k=4))}"
        f"Z{random.choice(string.digits + string.ascii_uppercase)}"
    )


def rand_phone():
    return "9" + "".join(
        random.choices(string.digits, k=9)
    )


def rand_person_name():
    return (
        f"{random.choice(FIRST_NAMES)} "
        f"{random.choice(LAST_NAMES)}"
    )


def rand_company_name():
    return (
        f"{random.choice(LAST_NAMES)} "
        f"{random.choice(COMPANY_SUFFIX)}"
    )


def rand_item_name():
    return (
        f"{random.choice(ITEM_ADJ)} "
        f"{random.choice(ITEM_NOUN)}"
    )


def rand_date(start, end):
    delta = end - start

    return (
        start
        + timedelta(
            days=random.randint(0, delta.days),
            seconds=random.randint(0, 86399),
        )
    ).strftime("%Y-%m-%d")


def rand_datetime_str(start, end):
    delta = end - start

    return (
        start
        + timedelta(
            days=random.randint(0, delta.days),
            seconds=random.randint(0, 86399),
        )
    ).strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# INSERT BATCHES
# ============================================================

def insert_batches(conn, table, columns, row_iter, total):
    placeholders = ",".join(
        ["?"] * len(columns)
    )

    sql = (
        f"INSERT INTO {table} "
        f"({','.join(columns)}) "
        f"VALUES ({placeholders})"
    )

    cur = conn.cursor()
    buffer = []
    inserted = 0
    start_time = time.time()

    for row in row_iter:

        buffer.append(row)

        if len(buffer) >= BATCH_SIZE:

            cur.executemany(
                sql,
                buffer
            )

            inserted += len(buffer)
            buffer.clear()

    if buffer:

        cur.executemany(
            sql,
            buffer
        )

        inserted += len(buffer)

    conn.commit()

    print(
        f"  {table:<18} "
        f"+{inserted:>8,} rows "
        f"({time.time() - start_time:5.1f}s)"
    )

    return inserted


# ============================================================
# GENERATORS
# ============================================================

def gen_departments(n, used_departments):

    counter = 1

    for _ in range(n):

        def create_name():

            nonlocal counter

            if counter <= len(DEPT_NAMES):

                value = DEPT_NAMES[counter - 1]

            else:

                value = (
                    f"{random.choice(DEPT_NAMES)} "
                    f"{counter}"
                )

            counter += 1

            return value

        yield (
            unique_value(
                create_name,
                used_departments
            ),
        )


def gen_parties(n, used_names, used_gst):

    for _ in range(n):

        name = unique_value(
            rand_company_name,
            used_names
        )

        gst = unique_value(
            rand_gst_no,
            used_gst
        )

        yield (
            name,
            rand_phone(),
            f"{random.randint(1,999)}, "
            f"{random.choice(CITIES)}",
            gst,
            rand_datetime_str(
                DATE_START,
                DATE_END
            ),
        )


def gen_products(n, dept_names):

    for _ in range(n):

        margin = round(
            random.uniform(10, 40),
            2
        )

        gst = random.choice(
            [0, 5, 12, 18, 28]
        )

        yield (
            rand_item_name(),
            random.choice(dept_names),
            str(random.randint(1000, 9999)),
            random.choice(UNITS),
            margin,
            gst,
            random.randint(2, 20),
            rand_datetime_str(
                DATE_START,
                DATE_END
            ),
        )


def gen_items(n, dept_names):

    for _ in range(n):

        margin = round(
            random.uniform(10, 40),
            2
        )

        gst = random.choice(
            [0, 5, 12, 18, 28]
        )

        yield (
            rand_item_name(),
            random.choice(dept_names),
            str(random.randint(1000, 9999)),
            random.choice(UNITS),
            margin,
            gst,
            random.randint(2, 20),
            rand_datetime_str(
                DATE_START,
                DATE_END
            ),
            random.choice(SIZES),
        )


def gen_purchases(
    n,
    party_rows,
    dept_names,
    used_invoices,
    invoice_start,
):

    invoice_counter = invoice_start

    for _ in range(n):

        invoice = make_unique_invoice(
            used_invoices,
            invoice_counter
        )

        invoice_counter = int(
            invoice.replace("PINV", "")
        ) + 1

        party_name, party_phone, party_addr, party_gst = (
            random.choice(party_rows)
        )

        mode = random.choices(
            ["cash", "credit"],
            weights=[60, 40]
        )[0]

        buy = round(
            random.uniform(500, 50000),
            2
        )

        margin_pct = random.uniform(
            15,
            35
        )

        sell = round(
            buy * (
                1 + margin_pct / 100
            ),
            2
        )

        gst_rate = random.choice(
            [0, 2.5, 6, 9, 14]
        )

        with_gst = round(
            sell * (
                1 + 2 * gst_rate / 100
            ),
            2
        )

        yield (
            invoice,
            party_name,
            party_phone,
            party_addr,
            party_gst,
            rand_date(
                DATE_START,
                DATE_END
            ),
            random.choice(dept_names),
            mode,
            buy,
            sell,
            with_gst,
            gst_rate,
            gst_rate,
            0,
            rand_datetime_str(
                DATE_START,
                DATE_END
            ),
            None,
            round(
                random.uniform(0, 10),
                2
            ),
        )


def gen_purchase_items(
    n,
    purchase_ids,
    product_ids,
    dept_names,
):

    for _ in range(n):

        qty = random.randint(
            1,
            50
        )

        buy_price = round(
            random.uniform(50, 2000),
            2
        )

        margin = round(
            random.uniform(10, 40),
            2
        )

        sell_price = round(
            buy_price * (
                1 + margin / 100
            ),
            2
        )

        buy_total = round(
            buy_price * qty,
            2
        )

        sell_total = round(
            sell_price * qty,
            2
        )

        profit = round(
            sell_total - buy_total,
            2
        )

        gst_rate = random.choice(
            [0, 2.5, 6, 9]
        )

        cgst = round(
            sell_total * gst_rate / 100,
            2
        )

        sgst = cgst

        total_with_gst = round(
            sell_total
            + cgst
            + sgst,
            2
        )

        sold = round(
            random.uniform(
                0,
                qty
            ),
            2
        )

        yield (
            random.choice(
                purchase_ids
            ),
            random.choice(
                product_ids
            ) if random.random() < 0.85
            else None,
            rand_item_name(),
            random.choice(SIZES),
            qty,
            sold,
            buy_price,
            margin,
            sell_price,
            buy_total,
            sell_total,
            profit,
            cgst,
            sgst,
            0,
            total_with_gst,
            random.choice(dept_names),
            rand_datetime_str(
                DATE_START,
                DATE_END
            ),
            buy_price,
        )


def gen_purchase_borrow(
    n,
    purchase_ids,
    purchase_invoice_numbers,
):

    for _ in range(n):

        total = round(
            random.uniform(
                1000,
                60000
            ),
            2
        )

        status = random.choice(
            STATUSES
        )

        paid = (
            0
            if status == "Pending"
            else (
                total
                if status == "Paid"
                else round(
                    total
                    * random.uniform(
                        0.2,
                        0.8
                    ),
                    2
                )
            )
        )

        yield (
            random.choice(
                purchase_ids
            ),
            random.choice(
                purchase_invoice_numbers
            ),
            rand_company_name(),
            rand_phone(),
            total,
            paid,
            round(
                total - paid,
                2
            ),
            rand_date(
                DATE_START,
                DATE_END
            ),
            status,
            rand_datetime_str(
                DATE_START,
                DATE_END
            ),
            rand_datetime_str(
                DATE_START,
                DATE_END
            ),
        )


def gen_barcodes(
    n,
    purchase_item_ids,
    used_barcodes,
    barcode_start,
):

    barcode_counter = barcode_start

    for _ in range(n):

        code = make_unique_barcode(
            used_barcodes,
            barcode_counter
        )

        barcode_counter = int(
            code.replace("BC", "")
        ) + 1

        status = random.choices(
            ["available", "sold"],
            weights=[35, 65]
        )[0]

        buy_price = round(
            random.uniform(
                50,
                2000
            ),
            2
        )

        margin = round(
            random.uniform(
                10,
                40
            ),
            2
        )

        sell_price = round(
            buy_price
            * (
                1 + margin / 100
            ),
            2
        )

        yield (
            code,
            random.choice(
                purchase_item_ids
            ),
            rand_item_name(),
            random.choice(SIZES),
            rand_company_name(),
            sell_price,
            buy_price,
            margin,
            status,
            rand_datetime_str(
                DATE_START,
                DATE_END
            ),
            rand_datetime_str(
                DATE_START,
                DATE_END
            )
            if status == "sold"
            else None,
        )


def gen_sales(
    n,
    used_bills,
    bill_start,
):

    bill_counter = bill_start

    for _ in range(n):

        bill = make_unique_bill(
            used_bills,
            bill_counter
        )

        bill_counter = int(
            bill.replace("SINV", "")
        ) + 1

        mode = random.choices(
            ["cash", "credit"],
            weights=[70, 30]
        )[0]

        buy = round(
            random.uniform(
                200,
                20000
            ),
            2
        )

        margin_pct = random.uniform(
            15,
            35
        )

        sell = round(
            buy
            * (
                1 + margin_pct / 100
            ),
            2
        )

        discount = round(
            random.uniform(
                0,
                sell * 0.1
            ),
            2
        )

        profit = round(
            sell
            - buy
            - discount,
            2
        )

        yield (
            bill,
            rand_person_name(),
            rand_phone(),
            rand_date(
                DATE_START,
                DATE_END
            ),
            mode,
            random.choice(
                PAYMENT_MODES
            ),
            sell,
            buy,
            profit,
            discount,
            rand_datetime_str(
                DATE_START,
                DATE_END
            ),
            None,
        )


def gen_sale_items(
    n,
    sale_ids,
    product_ids,
    purchase_item_ids,
    barcode_codes,
):

    for _ in range(n):

        qty = random.randint(
            1,
            10
        )

        buy_price = round(
            random.uniform(
                50,
                2000
            ),
            2
        )

        margin = round(
            random.uniform(
                10,
                40
            ),
            2
        )

        sell_price = round(
            buy_price
            * (
                1 + margin / 100
            ),
            2
        )

        buy_total = round(
            buy_price * qty,
            2
        )

        sell_total = round(
            sell_price * qty,
            2
        )

        discount = round(
            random.uniform(
                0,
                sell_total * 0.1
            ),
            2
        )

        profit = round(
            sell_total
            - buy_total
            - discount,
            2
        )

        use_barcode = (
            bool(barcode_codes)
            and random.random() < 0.5
        )

        yield (
            random.choice(
                sale_ids
            ),
            random.choice(
                product_ids
            ) if random.random() < 0.85
            else None,
            rand_item_name(),
            random.choice(SIZES),
            qty,
            buy_price,
            margin,
            sell_price,
            buy_total,
            sell_total,
            profit,
            discount,
            rand_datetime_str(
                DATE_START,
                DATE_END
            ),
            random.choice(
                purchase_item_ids
            ) if random.random() < 0.6
            else None,
            random.choice(
                barcode_codes
            ) if use_barcode
            else None,
        )


def gen_sales_borrow(
    n,
    sale_ids,
    sales_bill_numbers,
):

    for _ in range(n):

        total = round(
            random.uniform(
                500,
                30000
            ),
            2
        )

        status = random.choice(
            STATUSES
        )

        received = (
            0
            if status == "Pending"
            else (
                total
                if status == "Paid"
                else round(
                    total
                    * random.uniform(
                        0.2,
                        0.8
                    ),
                    2
                )
            )
        )

        yield (
            random.choice(
                sale_ids
            ),
            random.choice(
                sales_bill_numbers
            ),
            rand_person_name(),
            rand_phone(),
            total,
            received,
            round(
                total - received,
                2
            ),
            rand_date(
                DATE_START,
                DATE_END
            ),
            status,
            rand_datetime_str(
                DATE_START,
                DATE_END
            ),
            rand_datetime_str(
                DATE_START,
                DATE_END
            ),
        )


def gen_payments(
    n,
    purchase_borrow_ids,
    sales_borrow_ids,
):

    for _ in range(n):

        borrow_type = random.choice(
            ["purchase", "sales"]
        )

        borrow_id = (
            random.choice(
                purchase_borrow_ids
            )
            if borrow_type == "purchase"
            else random.choice(
                sales_borrow_ids
            )
        )

        yield (
            borrow_type,
            borrow_id,
            round(
                random.uniform(
                    100,
                    20000
                ),
                2
            ),
            rand_date(
                DATE_START,
                DATE_END
            ),
            random.choice(
                PAYMENT_MODES
            ),
            f"REF{random.randint(100000, 999999)}",
            "Auto-generated test payment",
            rand_datetime_str(
                DATE_START,
                DATE_END
            ),
        )


def gen_purchase_returns(
    n,
    dept_names,
    used_returns,
    return_start,
    purchase_invoice_numbers,
    barcode_codes,
):

    return_counter = return_start

    for _ in range(n):

        return_bill = make_unique_purchase_return(
            used_returns,
            return_counter
        )

        return_counter = int(
            return_bill.replace(
                "PRET",
                ""
            )
        ) + 1

        qty = random.randint(
            1,
            20
        )

        buy = round(
            random.uniform(
                50,
                2000
            ),
            2
        )

        yield (
            return_bill,
            rand_date(
                DATE_START,
                DATE_END
            ),
            rand_company_name(),
            rand_item_name(),
            random.choice(SIZES),
            qty,
            buy,
            round(
                buy * qty,
                2
            ),
            random.choice(
                barcode_codes
            ) if barcode_codes else None,
            random.choice(
                purchase_invoice_numbers
            ),
            "purchase_items",
            random.randint(
                1,
                100000
            ),
            random.choice(
                [
                    "Damaged",
                    "Wrong item",
                    "Excess stock",
                    "Quality issue",
                ]
            ),
            random.choice(
                dept_names
            ),
        )


def gen_sales_returns(
    n,
    used_returns,
    return_start,
    sales_bill_numbers,
    barcode_codes,
):

    return_counter = return_start

    for _ in range(n):

        return_bill = make_unique_sales_return(
            used_returns,
            return_counter
        )

        return_counter = int(
            return_bill.replace(
                "SRET",
                ""
            )
        ) + 1

        qty = random.randint(
            1,
            10
        )

        sell = round(
            random.uniform(
                100,
                3000
            ),
            2
        )

        yield (
            return_bill,
            rand_date(
                DATE_START,
                DATE_END
            ),
            rand_person_name(),
            rand_phone(),
            rand_item_name(),
            random.choice(SIZES),
            qty,
            sell,
            round(
                sell * qty,
                2
            ),
            random.choice(
                barcode_codes
            ) if barcode_codes else None,
            random.choice(
                sales_bill_numbers
            ),
            "sale_items",
            random.randint(
                1,
                200000
            ),
            random.choice(
                [
                    "Size issue",
                    "Not satisfied",
                    "Wrong item",
                    "Defective",
                ]
            ),
        )


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Generate bulk test data without "
            "duplicating existing identifiers."
        )
    )

    parser.add_argument(
        "--db-path",
        default=os.path.join(
            "DATABASE",
            "purchase_tracker.db"
        ),
    )

    parser.add_argument(
        "--total",
        type=int,
        default=None,
        help=(
            "Override total row count. "
            "Scales all table counts proportionally."
        ),
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducible data.",
    )

    parser.add_argument(
        "--wipe",
        action="store_true",
        help="Delete existing rows first.",
    )

    args = parser.parse_args()

    if args.seed is not None:
        random.seed(
            args.seed
        )

    counts = dict(
        DEFAULT_COUNTS
    )

    if args.total:

        base_total = sum(
            DEFAULT_COUNTS.values()
        )

        scale = (
            args.total
            / base_total
        )

        counts = {
            key: max(
                1,
                round(
                    value * scale
                )
            )
            for key, value
            in DEFAULT_COUNTS.items()
        }

    grand_total = sum(
        counts.values()
    )

    print(
        f"Target DB: {args.db_path}"
    )

    print(
        f"Planned new rows: "
        f"{grand_total:,}"
    )

    conn = connect(
        args.db_path
    )

    ensure_schema(
        conn
    )

    if args.wipe:

        wipe(
            conn
        )

    start_time = time.time()


    # ========================================================
    # LOAD EXISTING UNIQUE VALUES
    # ========================================================

    print(
        "\nChecking existing data "
        "to prevent duplicates..."
    )

    used_departments = existing_values(
        conn,
        "departments",
        "name"
    )

    used_party_names = existing_values(
        conn,
        "parties",
        "name"
    )

    used_gst_numbers = existing_values(
        conn,
        "parties",
        "gst_no"
    )

    used_invoices = existing_values(
        conn,
        "purchases",
        "invoice_no"
    )

    used_bills = existing_values(
        conn,
        "sales",
        "bill_no"
    )

    used_barcodes = existing_values(
        conn,
        "barcodes",
        "code"
    )

    used_purchase_returns = existing_values(
        conn,
        "purchase_returns",
        "returnBillNo"
    )

    used_sales_returns = existing_values(
        conn,
        "sales_returns",
        "returnBillNo"
    )

    print(
        f"Existing purchase invoices: "
        f"{len(used_invoices):,}"
    )

    print(
        f"Existing sales bills: "
        f"{len(used_bills):,}"
    )

    print(
        f"Existing barcodes: "
        f"{len(used_barcodes):,}"
    )


    # ========================================================
    # MASTER TABLES
    # ========================================================

    print(
        "\nMaster tables:"
    )

    insert_batches(
        conn,
        "departments",
        ["name"],
        gen_departments(
            counts["departments"],
            used_departments
        ),
        counts["departments"],
    )

    dept_names = [
        row["name"]
        for row in conn.execute(
            "SELECT name FROM departments"
        ).fetchall()
    ]


    insert_batches(
        conn,
        "parties",
        [
            "name",
            "seller_no",
            "address",
            "gst_no",
            "created_at",
        ],
        gen_parties(
            counts["parties"],
            used_party_names,
            used_gst_numbers,
        ),
        counts["parties"],
    )

    party_rows = [
        (
            row["name"],
            row["seller_no"],
            row["address"],
            row["gst_no"],
        )
        for row in conn.execute(
            """
            SELECT
                name,
                seller_no,
                address,
                gst_no
            FROM parties
            """
        ).fetchall()
    ]


    prod_base = max_id(
        conn,
        "products"
    )

    insert_batches(
        conn,
        "products",
        [
            "name",
            "department",
            "hsn",
            "unit",
            "default_margin",
            "default_gst",
            "min_stock",
            "created_at",
        ],
        gen_products(
            counts["products"],
            dept_names
        ),
        counts["products"],
    )

    product_ids = list(
        range(
            prod_base + 1,
            prod_base
            + counts["products"]
            + 1,
        )
    )


    insert_batches(
        conn,
        "items",
        [
            "name",
            "department",
            "hsn",
            "unit",
            "defaultMargin",
            "defaultGST",
            "min_stock",
            "createdAt",
            "size",
        ],
        gen_items(
            counts["items"],
            dept_names
        ),
        counts["items"],
    )


    # ========================================================
    # PURCHASES
    # ========================================================

    print(
        "\nPurchases side:"
    )

    purchase_invoice_start = (
        max(
            [
                int(
                    value[4:]
                )
                for value
                in used_invoices
                if value.startswith(
                    "PINV"
                )
                and value[4:].isdigit()
            ]
            or [99999]
        )
        + 1
    )

    pur_base = max_id(
        conn,
        "purchases"
    )

    insert_batches(
        conn,
        "purchases",
        [
            "invoice_no",
            "party",
            "seller_no",
            "seller_address",
            "seller_gst_no",
            "date",
            "department",
            "mode",
            "total_buy",
            "total_sell",
            "total_with_gst",
            "cgst_rate",
            "sgst_rate",
            "igst_rate",
            "created_at",
            "voucher_id",
            "discount",
        ],
        gen_purchases(
            counts["purchases"],
            party_rows,
            dept_names,
            used_invoices,
            purchase_invoice_start,
        ),
        counts["purchases"],
    )

    purchase_ids = list(
        range(
            pur_base + 1,
            pur_base
            + counts["purchases"]
            + 1,
        )
    )


    purchase_invoice_numbers = list(
        used_invoices
    )


    pi_base = max_id(
        conn,
        "purchase_items"
    )

    insert_batches(
        conn,
        "purchase_items",
        [
            "purchase_id",
            "product_id",
            "item",
            "size",
            "qty",
            "sold",
            "buy_price",
            "margin",
            "sell_price",
            "buy_total",
            "sell_total",
            "profit",
            "cgst",
            "sgst",
            "igst",
            "total_with_gst",
            "department",
            "created_at",
            "original_buy_price",
        ],
        gen_purchase_items(
            counts["purchase_items"],
            purchase_ids,
            product_ids,
            dept_names,
        ),
        counts["purchase_items"],
    )

    purchase_item_ids = list(
        range(
            pi_base + 1,
            pi_base
            + counts["purchase_items"]
            + 1,
        )
    )


    pb_base = max_id(
        conn,
        "purchase_borrow"
    )

    insert_batches(
        conn,
        "purchase_borrow",
        [
            "purchase_id",
            "invoice_no",
            "party_name",
            "party_phone",
            "total_amount",
            "paid_amount",
            "balance_amount",
            "due_date",
            "status",
            "created_at",
            "updated_at",
        ],
        gen_purchase_borrow(
            counts["purchase_borrow"],
            purchase_ids,
            purchase_invoice_numbers,
        ),
        counts["purchase_borrow"],
    )

    purchase_borrow_ids = list(
        range(
            pb_base + 1,
            pb_base
            + counts["purchase_borrow"]
            + 1,
        )
    )


    barcode_start = (
        max(
            [
                int(
                    value[2:]
                )
                for value
                in used_barcodes
                if value.startswith(
                    "BC"
                )
                and value[2:].isdigit()
            ]
            or [899999]
        )
        + 1
    )

    bc_base = max_id(
        conn,
        "barcodes"
    )

    insert_batches(
        conn,
        "barcodes",
        [
            "code",
            "purchase_item_id",
            "product_name",
            "size",
            "party",
            "sell_price",
            "buy_price",
            "margin",
            "status",
            "created_at",
            "sold_at",
        ],
        gen_barcodes(
            counts["barcodes"],
            purchase_item_ids,
            used_barcodes,
            barcode_start,
        ),
        counts["barcodes"],
    )

    barcode_codes = list(
        used_barcodes
    )


    # ========================================================
    # SALES
    # ========================================================

    print(
        "\nSales side:"
    )

    sales_bill_start = (
        max(
            [
                int(
                    value[4:]
                )
                for value
                in used_bills
                if value.startswith(
                    "SINV"
                )
                and value[4:].isdigit()
            ]
            or [199999]
        )
        + 1
    )

    sale_base = max_id(
        conn,
        "sales"
    )

    insert_batches(
        conn,
        "sales",
        [
            "bill_no",
            "customer_name",
            "customer_no",
            "date",
            "mode",
            "payment_mode",
            "total_sell",
            "total_buy",
            "total_profit",
            "discount",
            "created_at",
            "voucher_id",
        ],
        gen_sales(
            counts["sales"],
            used_bills,
            sales_bill_start,
        ),
        counts["sales"],
    )

    sale_ids = list(
        range(
            sale_base + 1,
            sale_base
            + counts["sales"]
            + 1,
        )
    )

    sales_bill_numbers = list(
        used_bills
    )


    insert_batches(
        conn,
        "sale_items",
        [
            "sale_id",
            "product_id",
            "item",
            "size",
            "qty",
            "buy_price",
            "margin",
            "sell_price",
            "buy_total",
            "sell_total",
            "profit",
            "discount",
            "created_at",
            "purchase_item_id",
            "barcode_code",
        ],
        gen_sale_items(
            counts["sale_items"],
            sale_ids,
            product_ids,
            purchase_item_ids,
            barcode_codes,
        ),
        counts["sale_items"],
    )


    sb_base = max_id(
        conn,
        "sales_borrow"
    )

    insert_batches(
        conn,
        "sales_borrow",
        [
            "sale_id",
            "bill_no",
            "customer_name",
            "customer_phone",
            "total_amount",
            "received_amount",
            "balance_amount",
            "due_date",
            "status",
            "created_at",
            "updated_at",
        ],
        gen_sales_borrow(
            counts["sales_borrow"],
            sale_ids,
            sales_bill_numbers,
        ),
        counts["sales_borrow"],
    )

    sales_borrow_ids = list(
        range(
            sb_base + 1,
            sb_base
            + counts["sales_borrow"]
            + 1,
        )
    )


    # ========================================================
    # PAYMENTS
    # ========================================================

    print(
        "\nPayments & returns:"
    )

    insert_batches(
        conn,
        "payments",
        [
            "borrow_type",
            "borrow_id",
            "amount",
            "payment_date",
            "payment_mode",
            "reference_no",
            "notes",
            "created_at",
        ],
        gen_payments(
            counts["payments"],
            purchase_borrow_ids,
            sales_borrow_ids,
        ),
        counts["payments"],
    )


    # ========================================================
    # PURCHASE RETURNS
    # ========================================================

    purchase_return_start = (
        max(
            [
                int(
                    value[4:]
                )
                for value
                in used_purchase_returns
                if value.startswith(
                    "PRET"
                )
                and value[4:].isdigit()
            ]
            or [0]
        )
        + 1
    )

    insert_batches(
        conn,
        "purchase_returns",
        [
            "returnBillNo",
            "date",
            "party",
            "item",
            "size",
            "qty",
            "buy",
            "buyTotal",
            "baseCode",
            "originalInvoiceNo",
            "originalTable",
            "originalId",
            "reason",
            "department",
        ],
        gen_purchase_returns(
            counts["purchase_returns"],
            dept_names,
            used_purchase_returns,
            purchase_return_start,
            purchase_invoice_numbers,
            barcode_codes,
        ),
        counts["purchase_returns"],
    )


    # ========================================================
    # SALES RETURNS
    # ========================================================

    sales_return_start = (
        max(
            [
                int(
                    value[4:]
                )
                for value
                in used_sales_returns
                if value.startswith(
                    "SRET"
                )
                and value[4:].isdigit()
            ]
            or [0]
        )
        + 1
    )

    insert_batches(
        conn,
        "sales_returns",
        [
            "returnBillNo",
            "date",
            "customerName",
            "customerNo",
            "item",
            "size",
            "qty",
            "sellUnit",
            "sellTotal",
            "baseCode",
            "originalBillNo",
            "originalTable",
            "originalId",
            "reason",
        ],
        gen_sales_returns(
            counts["sales_returns"],
            used_sales_returns,
            sales_return_start,
            sales_bill_numbers,
            barcode_codes,
        ),
        counts["sales_returns"],
    )


    conn.close()

    elapsed = (
        time.time()
        - start_time
    )

    print(
        f"\nDone."
    )

    print(
        f"Inserted "
        f"{grand_total:,} NEW rows."
    )

    print(
        f"Existing data was preserved."
    )

    print(
        f"Time: {elapsed:.1f}s"
    )

    print(
        f"Database: {args.db_path}"
    )


if __name__ == "__main__":
    main()