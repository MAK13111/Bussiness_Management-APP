from typing import Dict, List

from core.db import get_conn

class VoucherEngine:
    @staticmethod
    def generate_voucher_number(voucher_type: str) -> str:
        prefix_map = {
            'PAYMENT': 'PY-', 'RECEIPT': 'R-', 'CONTRA': 'C-',
            'JOURNAL': 'J-', 'PURCHASE': 'P-', 'SALES': 'S-',
            'SALESRET': 'SR-', 'PURCHASERET': 'PR-',
            'CREDITNOTE': 'CN-', 'DEBITNOTE': 'DN-'
        }
        prefix = prefix_map.get(voucher_type, 'V-')
        with get_conn() as conn:
            vt_row = conn.execute(
                "SELECT id FROM voucher_types WHERE code = ?", (voucher_type,)
            ).fetchone()
            if not vt_row:
                raise ValueError(f"Unknown voucher type code: {voucher_type}")
            result = conn.execute("""
                SELECT MAX(voucher_number) as max_num
                FROM vouchers
                WHERE voucher_type_id = ?
            """, (vt_row['id'],)).fetchone()
            max_num_str = result['max_num'] if result and result['max_num'] else None
            next_num = int(max_num_str[len(prefix):]) + 1 if max_num_str else 1
            return f"{prefix}{str(next_num).zfill(6)}"

    @staticmethod
    def create_voucher(data: Dict, conn=None) -> Dict:
        if conn is None:
            with get_conn() as conn:
                return VoucherEngine._create_voucher_internal(data, conn)
        else:
            return VoucherEngine._create_voucher_internal(data, conn)

    @staticmethod
    def _create_voucher_internal(data, conn):
        total_debit = sum(e.get('debit', 0) for e in data['entries'])
        total_credit = sum(e.get('credit', 0) for e in data['entries'])
        # A voucher with only ONE entry (e.g. the From/To journal vouchers,
        # which are saved as two separate single-sided vouchers) is allowed
        # to be one-sided on purpose — only multi-entry vouchers must balance.
        if len(data['entries']) > 1 and abs(total_debit - total_credit) > 0.01:
            raise ValueError(f"Debit ({total_debit}) != Credit ({total_credit})")

        # generate_voucher_number() reads MAX(...)+1 with no locking, so two
        # near-simultaneous requests can compute the same number. voucher_number
        # is UNIQUE, so retry a few times on collision instead of crashing.
        #
        # Postgres note: unlike sqlite, a failed INSERT poisons the whole
        # transaction until it's rolled back -- you can't just try the next
        # insert on the same connection. Each attempt runs inside its own
        # SAVEPOINT so a collision only undoes that attempt, not the entire
        # (possibly caller-owned) transaction.
        import psycopg2.errors as _pg_errors
        voucher_id = None
        for attempt in range(5):
            voucher_number = VoucherEngine.generate_voucher_number(data['voucher_type'])
            conn.savepoint("voucher_insert")
            try:
                # Resolve voucher_types.code → voucher_type_id
                vt_row = conn.execute(
                    "SELECT id FROM voucher_types WHERE code = ?",
                    (data['voucher_type'],)
                ).fetchone()
                if not vt_row:
                    raise ValueError(f"Unknown voucher type code: {data['voucher_type']}")
                voucher_type_id = vt_row['id']
                cursor = conn.execute("""
                    INSERT INTO vouchers
                    (voucher_number, voucher_type_id, date, reference, narration, created_by, is_posted)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    voucher_number,
                    voucher_type_id,
                    data['date'],
                    data.get('reference', ''),
                    data.get('narration', ''),
                    data.get('created_by', 'admin'),
                    True
                ))
                voucher_id = cursor.lastrowid
                conn.release_savepoint("voucher_insert")
                break
            except _pg_errors.UniqueViolation:
                conn.rollback_to_savepoint("voucher_insert")
                if attempt == 4:
                    raise
                continue
        for entry in data['entries']:
            conn.execute("""
                INSERT INTO voucher_entries (voucher_id, ledger_id, debit, credit)
                VALUES (?, ?, ?, ?)
            """, (voucher_id, entry['ledger_id'], entry.get('debit', 0), entry.get('credit', 0)))
        for stock in data.get('stock_entries', []):
            conn.execute("""
                INSERT INTO stock_ledger
                (voucher_id, stock_item_id, quantity_in, quantity_out, rate, amount)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                voucher_id,
                stock['stock_item_id'],
                stock.get('quantity_in', 0),
                stock.get('quantity_out', 0),
                stock.get('rate', 0),
                stock.get('amount', 0)
            ))
        # No commit here — whichever get_conn() owns this connection (either
        # opened inside create_voucher() above, or the caller's own
        # transaction when an external conn is passed in) commits once on
        # exit. Committing early here broke atomicity with the rest of the
        # caller's transaction whenever an external conn was used.
        return {"voucher_id": voucher_id, "voucher_number": voucher_number}

    @staticmethod
    def get_voucher(voucher_id: int) -> Dict:
        with get_conn() as conn:
            voucher = conn.execute("""
                SELECT v.*, vt.code as voucher_type, vt.name as voucher_type_name
                FROM vouchers v
                LEFT JOIN voucher_types vt ON vt.id = v.voucher_type_id
                WHERE v.id=?
            """, (voucher_id,)).fetchone()
            if not voucher:
                return None
            entries = conn.execute("""
                SELECT ve.*, l.name as ledger_name
                FROM voucher_entries ve
                JOIN ledgers l ON l.id = ve.ledger_id
                WHERE ve.voucher_id = ?
            """, (voucher_id,)).fetchall()
            return dict(voucher) | {"entries": [dict(e) for e in entries]}

    @staticmethod
    def update_voucher(voucher_id: int, data: Dict, conn=None) -> Dict:
        def _do_update(c):
            existing = c.execute("SELECT * FROM vouchers WHERE id=?", (voucher_id,)).fetchone()
            if not existing:
                raise ValueError("Voucher not found")

            total_debit = sum(e.get('debit', 0) for e in data['entries'])
            total_credit = sum(e.get('credit', 0) for e in data['entries'])
            if len(data['entries']) > 1 and abs(total_debit - total_credit) > 0.01:
                raise ValueError(f"Debit ({total_debit}) != Credit ({total_credit})")

            c.execute("""
                UPDATE vouchers
                SET date=?, reference=?, narration=?
                WHERE id=?
            """, (
                data['date'],
                data.get('reference', ''),
                data.get('narration', ''),
                voucher_id
            ))

            c.execute("DELETE FROM voucher_entries WHERE voucher_id=?", (voucher_id,))
            for entry in data['entries']:
                c.execute("""
                    INSERT INTO voucher_entries (voucher_id, ledger_id, debit, credit)
                    VALUES (?, ?, ?, ?)
                """, (voucher_id, entry['ledger_id'], entry.get('debit', 0), entry.get('credit', 0)))

            return {"voucher_id": voucher_id, "voucher_number": existing['voucher_number']}

        if conn is not None:
            return _do_update(conn)
        else:
            with get_conn() as connection:
                res = _do_update(connection)
                connection.commit()
                return res


    @staticmethod
    def _get_net_profit_loss(as_on_date: str = None, conn=None) -> float:
        """Single bulk query — no more per-group loops."""
        if conn is None:
            with get_conn() as conn:
                return VoucherEngine._get_net_profit_loss(as_on_date, conn)
        date_filter = "AND v.date <= ?" if as_on_date else ""
        params = [as_on_date] if as_on_date else []
        result = conn.execute(f"""
            SELECT
                COALESCE(SUM(CASE WHEN ag.group_type IN ('Income','Revenue')
                               THEN ve.credit - ve.debit ELSE 0 END), 0) AS total_income,
                COALESCE(SUM(CASE WHEN ag.group_type IN ('Expense','Cost')
                               THEN ve.debit - ve.credit ELSE 0 END), 0) AS total_expenses
            FROM ledgers l
            JOIN account_groups ag ON ag.id = l.group_id
            JOIN voucher_entries ve ON ve.ledger_id = l.id
            JOIN vouchers v ON v.id = ve.voucher_id
            WHERE ag.group_type IN ('Income','Revenue','Expense','Cost')
            {date_filter}
        """, params).fetchone()
        total_income = float(result['total_income'] if result else 0)
        total_expenses = float(result['total_expenses'] if result else 0)
        closing_stock = VoucherEngine.get_stock_value(conn)
        return total_income + closing_stock - total_expenses

    @staticmethod
    def _get_ledger_balance(ledger_id: int, as_on_date: str = None, conn=None) -> Dict:
        if conn is None:
            with get_conn() as conn:
                return VoucherEngine._get_ledger_balance(ledger_id, as_on_date, conn)
        ledger = conn.execute("SELECT * FROM ledgers WHERE id=?", (ledger_id,)).fetchone()
        if not ledger:
            return {"balance": 0, "balance_type": "Debit"}
        opening = ledger['opening_balance'] or 0
        bal_type = ledger['balance_type']
        query = """
            SELECT COALESCE(SUM(debit), 0) as total_debit,
                   COALESCE(SUM(credit), 0) as total_credit
            FROM voucher_entries ve
            JOIN vouchers v ON v.id = ve.voucher_id
            WHERE ve.ledger_id = ?
        """
        params = [ledger_id]
        if as_on_date:
            query += " AND v.date <= ?"
            params.append(as_on_date)
        res = conn.execute(query, params).fetchone()
        total_debit = res['total_debit'] if res else 0
        total_credit = res['total_credit'] if res else 0
        if bal_type == 'Debit':
            balance = opening + total_debit - total_credit
        else:
            balance = opening + total_credit - total_debit
        return {"balance": balance, "balance_type": bal_type}

    @staticmethod
    def _get_group_name(group_id: int, conn=None) -> str:
        if not group_id:
            return "Sundry"
        if conn is None:
            with get_conn() as conn:
                return VoucherEngine._get_group_name(group_id, conn)
        res = conn.execute("SELECT name FROM account_groups WHERE id=?", (group_id,)).fetchone()
        return res['name'] if res else "Sundry"

    @staticmethod
    def get_stock_value(conn=None) -> float:
        if conn is None:
            with get_conn() as conn:
                return VoucherEngine.get_stock_value(conn)
        # Fast path: read from the dashboard_data cache (updated by the
        # background dashboard refresh job). This avoids a full scan of the
        # products table (21L+ rows = ~900ms). Falls back to the full scan
        # only when the cache row is missing.
        try:
            cached = conn.execute(
                "SELECT stock_value FROM dashboard_data WHERE period = 'alltime' LIMIT 1"
            ).fetchone()
            if cached is not None and cached['stock_value'] is not None:
                return float(cached['stock_value'])
        except Exception:
            pass  # cache miss — fall through to full scan

        # Fallback: full products aggregate (slow but always correct)
        row = conn.execute("""
            SELECT COALESCE(SUM(
                CASE WHEN qty > 0 AND remaining > 0
                     THEN total_buy_price * remaining * 1.0 / qty ELSE 0 END
            ), 0) as total
            FROM products
            WHERE product_id IS NOT NULL
        """).fetchone()
        return row['total'] or 0.0


    @staticmethod
    def get_balance_sheet(as_on_date: str = None) -> Dict:
        """Bulk query — replaces O(N) per-ledger loops with 2 DB roundtrips."""
        with get_conn() as conn:
            date_filter = "AND v.date <= ?" if as_on_date else ""
            params = [as_on_date] if as_on_date else []

            # One query: opening balance + all voucher movements per ledger,
            # joined with account_group so we can bucket in Python.
            rows = conn.execute(f"""
                SELECT
                    l.id,
                    l.name,
                    l.opening_balance,
                    l.balance_type,
                    ag.name  AS group_name,
                    ag.group_type,
                    COALESCE(SUM(ve.debit),  0) AS total_debit,
                    COALESCE(SUM(ve.credit), 0) AS total_credit
                FROM ledgers l
                LEFT JOIN account_groups ag ON ag.id = l.group_id
                LEFT JOIN voucher_entries ve ON ve.ledger_id = l.id
                LEFT JOIN vouchers v ON v.id = ve.voucher_id
                    {date_filter}
                WHERE l.is_active = TRUE
                GROUP BY l.id, l.name, l.opening_balance, l.balance_type,
                         ag.name, ag.group_type
                ORDER BY l.name
            """, params).fetchall()

            assets, liabilities, equity = [], [], []
            for r in rows:
                gt = r['group_type'] or ''
                # Skip nominal (P&L) accounts — Sales Accounts, Purchase Accounts,
                # Direct/Indirect Income & Expenses.  Their net effect is already
                # captured through the "Net Profit / Net Loss" equity entry below.
                # Including them raw here causes double-counting and breaks the
                # Assets = Liabilities + Equity identity.
                if gt in ('Income', 'Revenue', 'Expense', 'Cost'):
                    continue

                opening  = float(r['opening_balance'] or 0)
                bal_type = r['balance_type'] or 'Debit'
                td, tc   = float(r['total_debit'] or 0), float(r['total_credit'] or 0)
                balance  = (opening + td - tc) if bal_type == 'Debit' else (opening + tc - td)

                # Skip zero-balance ledgers — they add noise but no value
                if abs(balance) < 0.01:
                    continue

                # signed_balance: positive = normal side, negative = overdrawn/reversed
                # We store both the raw signed value (for correct totals) and abs for display.
                signed_balance = balance if bal_type == 'Debit' else -balance

                entry = {
                    "ledger":          r['name'],
                    "group":           r['group_name'] or 'Sundry',
                    "balance":         abs(balance),      # display magnitude (always ≥ 0)
                    "signed_balance":  signed_balance,    # used for correct Total Assets math
                    "balance_type":    bal_type
                }
                if gt == 'Assets':
                    assets.append(entry)
                elif gt == 'Liabilities':
                    # In Tally, liability ledgers with a Debit balance (like GST Input / ITC)
                    # are displayed under Assets as Current Assets.
                    if bal_type == 'Debit' and balance > 0:
                        assets.append(entry)
                    else:
                        liabilities.append(entry)
                elif gt == 'Equity':
                    equity.append(entry)
                else:
                    # Unknown / unclassified — bucket by balance direction
                    if bal_type == 'Debit':
                        assets.append(entry)
                    else:
                        liabilities.append(entry)

            # Stock value — single aggregate, fast
            stock_value = VoucherEngine.get_stock_value(conn)
            if stock_value > 0:
                assets.append({
                    "ledger":         "Stock-in-Hand",
                    "group":          "Current Assets",
                    "balance":        stock_value,
                    "signed_balance": stock_value,
                    "balance_type":   "Debit"
                })

            # Net profit — single bulk query
            net_profit = VoucherEngine._get_net_profit_loss(as_on_date, conn)
            if abs(net_profit) > 0.001:
                if net_profit > 0:
                    equity.append({"ledger": "Net Profit", "group": "Equity",
                                   "balance": net_profit, "signed_balance": net_profit,
                                   "balance_type": "Credit"})
                else:
                    equity.append({"ledger": "Net Loss", "group": "Equity",
                                   "balance": abs(net_profit), "signed_balance": -abs(net_profit),
                                   "balance_type": "Debit"})

            # Total Assets = sum of SIGNED balances so that overdrawn (negative)
            # ledgers reduce the total instead of inflating it.
            total_assets      = sum(a['signed_balance'] for a in assets)
            total_liabilities = sum(l['balance'] if l['balance_type'] == 'Credit' else -l['balance'] for l in liabilities)
            total_equity      = sum(e['balance'] if e['balance_type'] == 'Credit'
                                    else -e['balance'] for e in equity)

            return {
                "assets": assets,
                "liabilities": liabilities,
                "equity": equity,
                "total_assets": total_assets,
                "total_liabilities": total_liabilities,
                "total_equity": total_equity
            }

    @staticmethod
    def get_trial_balance(as_on_date: str = None) -> List[Dict]:
        """Single bulk query — replaces O(N*2) per-ledger loops."""
        with get_conn() as conn:
            date_filter = "AND v.date <= ?" if as_on_date else ""
            params = [as_on_date] if as_on_date else []
            rows = conn.execute(f"""
                SELECT
                    l.name          AS ledger_name,
                    ag.name         AS group_name,
                    l.opening_balance,
                    l.balance_type,
                    COALESCE(SUM(ve.debit),  0) AS total_debit,
                    COALESCE(SUM(ve.credit), 0) AS total_credit
                FROM ledgers l
                LEFT JOIN account_groups ag ON ag.id = l.group_id
                LEFT JOIN voucher_entries ve ON ve.ledger_id = l.id
                LEFT JOIN vouchers v ON v.id = ve.voucher_id
                    {date_filter}
                WHERE l.is_active = TRUE
                GROUP BY l.id, l.name, ag.name, l.opening_balance, l.balance_type
                ORDER BY l.name
            """, params).fetchall()
            result = []
            for r in rows:
                opening  = float(r['opening_balance'] or 0)
                bal_type = r['balance_type'] or 'Debit'
                td, tc   = float(r['total_debit'] or 0), float(r['total_credit'] or 0)
                balance  = (opening + td - tc) if bal_type == 'Debit' else (opening + tc - td)

                # Tally standard display:
                # - Debit-type account, positive balance  → Debit column
                # - Debit-type account, negative balance  → Credit column (overdrawn/reversed)
                # - Credit-type account, positive balance → Credit column
                # - Credit-type account, negative balance → Debit column (reversed)
                if bal_type == 'Debit':
                    if balance >= 0:
                        debit_val, credit_val = balance, 0
                    else:
                        debit_val, credit_val = 0, abs(balance)   # Cash Cr balance (e.g. paid more than received)
                else:
                    if balance >= 0:
                        debit_val, credit_val = 0, balance
                    else:
                        debit_val, credit_val = abs(balance), 0   # reversed credit account

                result.append({
                    "ledger_name": r['ledger_name'],
                    "group_name":  r['group_name'] or 'Sundry',
                    "debit":  debit_val,
                    "credit": credit_val,
                })
            return result


    @staticmethod
    def get_profit_loss(from_date: str, to_date: str, closing_stock: float = None) -> Dict:
        """Single-pass bulk queries -- replaces O(N) per-group DB loops."""
        with get_conn() as conn:
            # One query covers all income groups: join account_groups directly
            # instead of looping over each group ID individually.
            income_rows = conn.execute("""
                SELECT l.name as ledger_name,
                       COALESCE(SUM(ve.credit) - SUM(ve.debit), 0) as balance
                FROM ledgers l
                JOIN account_groups ag ON ag.id = l.group_id
                JOIN voucher_entries ve ON ve.ledger_id = l.id
                JOIN vouchers v        ON v.id  = ve.voucher_id
                WHERE ag.group_type IN ('Income', 'Revenue')
                  AND v.date BETWEEN ? AND ?
                GROUP BY l.id, l.name
                HAVING COALESCE(SUM(ve.credit) - SUM(ve.debit), 0) > 0
            """, (from_date, to_date)).fetchall()
            income = [dict(r) for r in income_rows]

            # Caller (dashboard) usually already has this number from its own
            # purchase_items aggregate -- only recompute (another full-table
            # scan over purchase_items) if it wasn't handed to us.
            if closing_stock is None:
                closing_stock = VoucherEngine.get_stock_value(conn)
            if closing_stock > 0:
                income.append({"ledger_name": "Closing Stock", "balance": closing_stock})

            expense_rows = conn.execute("""
                SELECT l.name as ledger_name,
                       COALESCE(SUM(ve.debit) - SUM(ve.credit), 0) as balance
                FROM ledgers l
                JOIN account_groups ag ON ag.id = l.group_id
                JOIN voucher_entries ve ON ve.ledger_id = l.id
                JOIN vouchers v        ON v.id  = ve.voucher_id
                WHERE ag.group_type IN ('Expense', 'Cost')
                  AND v.date BETWEEN ? AND ?
                GROUP BY l.id, l.name
                HAVING COALESCE(SUM(ve.debit) - SUM(ve.credit), 0) > 0
            """, (from_date, to_date)).fetchall()
            expenses = [dict(r) for r in expense_rows]

            total_income = sum(i['balance'] for i in income)
            total_expenses = sum(e['balance'] for e in expenses)
            net = total_income - total_expenses
            return {
                "income": income,
                "expenses": expenses,
                "total_income": total_income,
                "total_expenses": total_expenses,
                "net_profit": net,
                "is_profit": net > 0
            }

    @staticmethod
    def get_ledger_statement(ledger_id: int = None, from_date: str = None, to_date: str = None) -> List[Dict]:
        with get_conn() as conn:
            query = """
                SELECT v.date, v.voucher_number, vt.code as voucher_type, v.narration,
                       ve.debit, ve.credit, l.name as ledger_name
                FROM voucher_entries ve
                JOIN vouchers v ON v.id = ve.voucher_id
                LEFT JOIN voucher_types vt ON vt.id = v.voucher_type_id
                JOIN ledgers l ON l.id = ve.ledger_id
                WHERE 1=1
            """
            params = []
            if ledger_id:
                query += " AND ve.ledger_id = ?"
                params.append(ledger_id)
            if from_date:
                query += " AND v.date >= ?"
                params.append(from_date)
            if to_date:
                query += " AND v.date <= ?"
                params.append(to_date)
            if ledger_id:
                query += " ORDER BY v.date, v.id"
            else:
                query += " ORDER BY l.name, v.date, v.id"
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def get_day_book(date_str: str) -> List[Dict]:
        """CTE-based pre-aggregation -- eliminates 2 correlated subqueries per row."""
        with get_conn() as conn:
            rows = conn.execute("""
                WITH day_vouchers AS (
                    -- Fetch only today's voucher IDs first (uses idx_vouchers_date)
                    SELECT v.id, v.voucher_number, vt.code as voucher_type, v.date,
                           v.reference, v.narration
                    FROM vouchers v
                    LEFT JOIN voucher_types vt ON vt.id = v.voucher_type_id
                    WHERE v.date = ?
                ),
                amounts AS (
                    -- One aggregation pass over just this day's entries
                    SELECT ve.voucher_id,
                           GREATEST(COALESCE(SUM(ve.debit),0), COALESCE(SUM(ve.credit),0)) as amount
                    FROM voucher_entries ve
                    WHERE ve.voucher_id IN (SELECT id FROM day_vouchers)
                    GROUP BY ve.voucher_id
                ),
                parties AS (
                    -- One pass to pick one party ledger per voucher
                    SELECT DISTINCT ON (ve.voucher_id) ve.voucher_id, l.name as party_name
                    FROM voucher_entries ve
                    JOIN ledgers l        ON l.id  = ve.ledger_id
                    JOIN account_groups ag ON ag.id = l.group_id
                    WHERE ve.voucher_id IN (SELECT id FROM day_vouchers)
                      AND ag.name IN ('Sundry Debtors', 'Sundry Creditors')
                    ORDER BY ve.voucher_id
                )
                SELECT dv.*, a.amount, p.party_name
                FROM day_vouchers dv
                LEFT JOIN amounts a  ON a.voucher_id = dv.id
                LEFT JOIN parties p  ON p.voucher_id = dv.id
                ORDER BY dv.id
            """, (date_str,)).fetchall()
            return [dict(r) for r in rows]
