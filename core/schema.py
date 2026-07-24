from datetime import datetime

from core.db import get_conn, _add_column_if_missing

def init_schema():
    with get_conn() as conn:
        # --- TALLY TABLES (unchanged) ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS account_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                parent_id INTEGER REFERENCES account_groups(id),
                group_type TEXT NOT NULL,
                nature TEXT,
                is_primary BOOLEAN DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ledgers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                group_id INTEGER REFERENCES account_groups(id),
                opening_balance REAL DEFAULT 0,
                balance_type TEXT CHECK (balance_type IN ('Debit','Credit')),
                contact_person TEXT, phone TEXT, email TEXT,
                address TEXT, gst_no TEXT, pan_no TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vouchers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                voucher_number TEXT UNIQUE NOT NULL,
                voucher_type TEXT NOT NULL,
                date TEXT NOT NULL,
                reference TEXT,
                narration TEXT,
                created_by TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                is_posted BOOLEAN DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS voucher_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                voucher_id INTEGER NOT NULL,
                ledger_id INTEGER NOT NULL,
                debit REAL DEFAULT 0,
                credit REAL DEFAULT 0,
                FOREIGN KEY (voucher_id) REFERENCES vouchers(id) ON DELETE CASCADE,
                FOREIGN KEY (ledger_id) REFERENCES ledgers(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS voucher_types (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                code TEXT UNIQUE NOT NULL,
                is_active BOOLEAN DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                group_id INTEGER,
                unit TEXT,
                opening_stock REAL DEFAULT 0,
                opening_value REAL DEFAULT 0,
                gst_rate REAL DEFAULT 0,
                hsn_code TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                voucher_id INTEGER REFERENCES vouchers(id),
                stock_item_id INTEGER REFERENCES stock_items(id),
                quantity_in REAL DEFAULT 0,
                quantity_out REAL DEFAULT 0,
                rate REAL DEFAULT 0,
                amount REAL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # --- NEW CORE TABLES ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS parties (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                seller_no TEXT,
                address TEXT,
                gst_no TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                department TEXT,
                hsn TEXT,
                unit TEXT,
                default_margin REAL DEFAULT 0,
                default_gst REAL DEFAULT 0,
                min_stock REAL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS purchases (
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
                FOREIGN KEY (voucher_id) REFERENCES vouchers(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS purchase_items (
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
                FOREIGN KEY (purchase_id) REFERENCES purchases(id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES products(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sales (
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
                voucher_id INTEGER,
                FOREIGN KEY (voucher_id) REFERENCES vouchers(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sale_items (
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
                FOREIGN KEY (sale_id) REFERENCES sales(id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES products(id)
            )
        """)
        _add_column_if_missing(conn, "sale_items", "purchase_item_id", "INTEGER")
        _add_column_if_missing(conn, "sale_items", "barcode_code", "TEXT")
        _add_column_if_missing(conn, "sale_items", "purchase_item_id", "INTEGER")
        _add_column_if_missing(conn, "sale_items", "barcode_code", "TEXT")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS purchase_borrow (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_id INTEGER NOT NULL,
                invoice_no TEXT,
                party_name TEXT,
                party_phone TEXT,
                total_amount REAL NOT NULL,
                paid_amount REAL DEFAULT 0,
                balance_amount REAL DEFAULT 0,
                due_date TEXT,
                status TEXT DEFAULT 'Pending' CHECK (status IN ('Pending','Partial','Paid')),
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (purchase_id) REFERENCES purchases(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sales_borrow (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sale_id INTEGER NOT NULL,
                bill_no TEXT,
                customer_name TEXT,
                customer_phone TEXT,
                total_amount REAL NOT NULL,
                received_amount REAL DEFAULT 0,
                balance_amount REAL DEFAULT 0,
                due_date TEXT,
                status TEXT DEFAULT 'Pending' CHECK (status IN ('Pending','Partial','Paid')),
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (sale_id) REFERENCES sales(id)
            )
        """)
        # NEW: Payments table for history
        conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                borrow_type TEXT NOT NULL CHECK (borrow_type IN ('purchase','sales')),
                borrow_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                payment_date TEXT NOT NULL,
                payment_mode TEXT CHECK (payment_mode IN ('Cash','UPI','Bank','Card','Other')),
                reference_no TEXT,
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Add due_date column if missing (for backward compatibility)
        _add_column_if_missing(conn, "purchase_borrow", "due_date", "TEXT")
        _add_column_if_missing(conn, "sales_borrow", "due_date", "TEXT")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS barcodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                purchase_item_id INTEGER,
                product_name TEXT,
                size TEXT,
                party TEXT,
                sell_price REAL,
                buy_price REAL,
                margin REAL,
                status TEXT DEFAULT 'available' CHECK (status IN ('available','sold')),
                created_at TEXT,
                sold_at TEXT,
                FOREIGN KEY (purchase_item_id) REFERENCES purchase_items(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS barcode_sequence (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_number INTEGER NOT NULL DEFAULT 9999
            )
        """)
        conn.execute("INSERT OR IGNORE INTO barcode_sequence (id, last_number) VALUES (1, 9999)")

        # Old legacy tables (cash_purchases, credit_purchases, cash_sells, credit_sells)
        # permanently removed — unused anywhere, was being drop+recreated empty every startup.
        for table in ["cash_purchases", "credit_purchases", "cash_sells", "credit_sells"]:
            conn.execute(f"DROP TABLE IF EXISTS {table}")

        # Other tables (departments, items, returns, accounts)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS departments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                department TEXT, hsn TEXT, unit TEXT,
                defaultMargin REAL DEFAULT 0,
                defaultGST REAL DEFAULT 0,
                min_stock REAL DEFAULT 0,
                createdAt TEXT
            )
        """)
        # Size distinguishes items with the same name (e.g. T-shirt size M vs L)
        _add_column_if_missing(conn, "items", "size", "TEXT")
        _add_column_if_missing(conn, "purchases", "seller_gst_no", "TEXT")
        # Supplier discount (%) applied on this bill's purchase cost — kept on
        # the header so it can be shown/restored correctly when editing later.
        _add_column_if_missing(conn, "purchases", "discount", "REAL DEFAULT 0")
        # Original per-unit price as typed by the user, before the supplier
        # discount was applied. buy_price stores the post-discount (effective)
        # cost used for totals/GST; original_buy_price is what margin/sell
        # price should be calculated from, and what the edit form should show.
        _add_column_if_missing(conn, "purchase_items", "original_buy_price", "REAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS purchase_returns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                returnBillNo TEXT, date TEXT, party TEXT,
                item TEXT, size TEXT, qty REAL, buy REAL,
                buyTotal REAL, baseCode TEXT, originalInvoiceNo TEXT,
                originalTable TEXT, originalId INTEGER,
                reason TEXT, department TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sales_returns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                returnBillNo TEXT, date TEXT, customerName TEXT,
                customerNo TEXT, item TEXT, size TEXT, qty REAL,
                sellUnit REAL, sellTotal REAL, baseCode TEXT,
                originalBillNo TEXT, originalTable TEXT,
                originalId INTEGER, reason TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS replace_bills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                replaceBillNo TEXT, date TEXT, customerName TEXT, customerNo TEXT,
                oldTotal REAL DEFAULT 0, newTotal REAL DEFAULT 0,
                difference REAL DEFAULT 0, note TEXT
            )
        """)
        _add_column_if_missing(conn, "replace_bills", "discount", "REAL DEFAULT 0")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS replace_bill_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                replace_bill_id INTEGER NOT NULL,
                side TEXT NOT NULL CHECK (side IN ('old','new')),
                item TEXT, size TEXT, qty REAL DEFAULT 1,
                sell_price REAL DEFAULT 0, sell_total REAL DEFAULT 0,
                barcode_code TEXT, purchase_item_id INTEGER,
                FOREIGN KEY (replace_bill_id) REFERENCES replace_bills(id) ON DELETE CASCADE,
                FOREIGN KEY (purchase_item_id) REFERENCES purchase_items(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                type TEXT DEFAULT 'cash',
                openingBalance REAL DEFAULT 0,
                currentBalance REAL DEFAULT 0,
                accountNo TEXT, ifsc TEXT,
                createdAt TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shop_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                shop_name TEXT DEFAULT '',
                address TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                gst_no TEXT DEFAULT '',
                footer_note TEXT DEFAULT ''
            )
        """)
        # Tiny single-row table used to remember how far the "self-heal missing
        # items" check (routes/items.py) has scanned into purchase_items, so it
        # only needs to look at rows added since last time instead of
        # re-scanning the whole table (100k+ rows) on every /api/items load.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                items_synced_upto INTEGER DEFAULT 0
            )
        """)
        conn.execute("INSERT OR IGNORE INTO app_state (id, items_synced_upto) VALUES (1, 0)")

        # Indexes -- critical at scale (1 lakh+ rows in purchase_items/sale_items).
        # Without these, every WHERE/JOIN/GROUP BY on date, item, or foreign keys
        # does a full table scan.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_purchases_date ON purchases(date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_purchases_mode ON purchases(mode)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_purchase_items_pid ON purchase_items(purchase_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_purchase_items_item ON purchase_items(item)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sales_mode ON sales(mode)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sale_items_sid ON sale_items(sale_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sale_items_item ON sale_items(item)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_voucher_entries_vid ON voucher_entries(voucher_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_voucher_entries_lid ON voucher_entries(ledger_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_vouchers_date ON vouchers(date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_barcodes_status ON barcodes(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_replace_bill_items_rbid ON replace_bill_items(replace_bill_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_purchase_returns_date ON purchase_returns(date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sales_returns_date ON sales_returns(date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_items_name_size ON items(name, size)")
        # Expression index matching LOWER(name)/LOWER(size) exactly as used in
        # the case-insensitive item-lookup queries (routes/items.py,
        # routes/purchases.py). A plain index on (name, size) can't be used
        # by those queries because LOWER() on the column defeats it -- this
        # is what makes the "self-heal missing items" check fast instead of
        # a full items-table scan per purchase_items row.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_items_name_size_ci ON items(LOWER(name), LOWER(COALESCE(size, '')))")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_purchase_items_item_size ON purchase_items(item, size)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_parties_name ON parties(name)")
        # Speeds up the Reports > Analyze > Sold Items view, which filters
        # purchase_items down to only rows with sold > 0 instead of pulling
        # the entire (100k+ row) table to the browser and filtering there.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_purchase_items_sold ON purchase_items(sold)")

        conn.commit()


def populate_defaults():
    with get_conn() as conn:
        # Same as before – populate account groups, ledgers, voucher types
        default_groups = [
            ('Capital Account', None, 'Equity', 'Credit', 1),
            ('Current Assets', None, 'Assets', 'Debit', 1),
            ('Current Liabilities', None, 'Liabilities', 'Credit', 1),
            ('Direct Income', None, 'Income', 'Credit', 1),
            ('Direct Expenses', None, 'Expense', 'Debit', 1),
            ('Indirect Income', None, 'Income', 'Credit', 1),
            ('Indirect Expenses', None, 'Expense', 'Debit', 1),
            ('Fixed Assets', None, 'Assets', 'Debit', 1),
            ('Bank Accounts', None, 'Assets', 'Debit', 0),
            ('Cash-in-Hand', None, 'Assets', 'Debit', 0),
            ('Sundry Debtors', None, 'Assets', 'Debit', 0),
            ('Sundry Creditors', None, 'Liabilities', 'Credit', 0),
            ('Duties & Taxes', None, 'Liabilities', 'Credit', 0),
            ('Sales Accounts', None, 'Income', 'Credit', 0),
            ('Purchase Accounts', None, 'Expense', 'Debit', 0),
            ('Stock-in-Hand', None, 'Assets', 'Debit', 0),
            ('Reserves & Surplus', None, 'Equity', 'Credit', 1),
        ]
        for name, parent, group_type, nature, is_primary in default_groups:
            conn.execute("""
                INSERT OR IGNORE INTO account_groups
                (name, parent_id, group_type, nature, is_primary)
                VALUES (?, ?, ?, ?, ?)
            """, (name, parent, group_type, nature, is_primary))

        cash_group = conn.execute("SELECT id FROM account_groups WHERE name='Cash-in-Hand'").fetchone()
        bank_group = conn.execute("SELECT id FROM account_groups WHERE name='Bank Accounts'").fetchone()
        capital_group = conn.execute("SELECT id FROM account_groups WHERE name='Capital Account'").fetchone()
        sales_group = conn.execute("SELECT id FROM account_groups WHERE name='Sales Accounts'").fetchone()
        purchase_group = conn.execute("SELECT id FROM account_groups WHERE name='Purchase Accounts'").fetchone()
        gst_group = conn.execute("SELECT id FROM account_groups WHERE name='Duties & Taxes'").fetchone()

        default_ledgers = [
            ('Cash', cash_group['id'] if cash_group else None, 0, 'Debit'),
            ('Bank Account', bank_group['id'] if bank_group else None, 0, 'Debit'),
            ('Capital', capital_group['id'] if capital_group else None, 0, 'Credit'),
            ('Sales', sales_group['id'] if sales_group else None, 0, 'Credit'),
            ('Purchase', purchase_group['id'] if purchase_group else None, 0, 'Debit'),
            ('GST Payable', gst_group['id'] if gst_group else None, 0, 'Credit'),
            ('GST Input', gst_group['id'] if gst_group else None, 0, 'Debit'),
            ('Discount Allowed', None, 0, 'Debit'),
            ('Discount Received', None, 0, 'Credit'),
        ]
        for name, group_id, balance, balance_type in default_ledgers:
            conn.execute("""
                INSERT OR IGNORE INTO ledgers
                (name, group_id, opening_balance, balance_type)
                VALUES (?, ?, ?, ?)
            """, (name, group_id, balance, balance_type))

        voucher_types = [
            ('Payment', 'PAYMENT'), ('Receipt', 'RECEIPT'), ('Contra', 'CONTRA'),
            ('Journal', 'JOURNAL'), ('Purchase', 'PURCHASE'), ('Sales', 'SALES'),
            ('Sales Return', 'SALESRET'), ('Purchase Return', 'PURCHASERET'),
            ('Credit Note', 'CREDITNOTE'), ('Debit Note', 'DEBITNOTE'),
        ]
        for name, code in voucher_types:
            conn.execute("""
                INSERT OR IGNORE INTO voucher_types (name, code) VALUES (?, ?)
            """, (name, code))

        # Ensure Cash and Bank ledgers exist in accounts table for backward compatibility
        cash_acc = conn.execute("SELECT id FROM accounts WHERE name='Cash'").fetchone()
        if not cash_acc:
            conn.execute("""
                INSERT INTO accounts (name, type, openingBalance, currentBalance, createdAt)
                VALUES ('Cash', 'cash', 0, 0, ?)
            """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
        bank_acc = conn.execute("SELECT id FROM accounts WHERE name='Bank'").fetchone()
        if not bank_acc:
            conn.execute("""
                INSERT INTO accounts (name, type, openingBalance, currentBalance, createdAt)
                VALUES ('Bank', 'bank', 0, 0, ?)
            """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
        conn.commit()

