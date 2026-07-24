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
            result = conn.execute("""
                SELECT MAX(CAST(SUBSTR(voucher_number, LENGTH(?) + 1) AS INTEGER)) as max_num
                FROM vouchers
                WHERE voucher_number LIKE ? || '%'
            """, (prefix, prefix)).fetchone()
            next_num = (result['max_num'] if result['max_num'] is not None else 0) + 1
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
        import sqlite3 as _sqlite3
        voucher_id = None
        for attempt in range(5):
            voucher_number = VoucherEngine.generate_voucher_number(data['voucher_type'])
            try:
                cursor = conn.execute("""
                    INSERT INTO vouchers
                    (voucher_number, voucher_type, date, reference, narration, created_by, is_posted)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    voucher_number,
                    data['voucher_type'],
                    data['date'],
                    data.get('reference', ''),
                    data.get('narration', ''),
                    data.get('created_by', 'admin'),
                    1
                ))
                voucher_id = cursor.lastrowid
                break
            except _sqlite3.IntegrityError:
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
            voucher = conn.execute("SELECT * FROM vouchers WHERE id=?", (voucher_id,)).fetchone()
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
    def update_voucher(voucher_id: int, data: Dict) -> Dict:
        with get_conn() as conn:
            existing = conn.execute("SELECT * FROM vouchers WHERE id=?", (voucher_id,)).fetchone()
            if not existing:
                raise ValueError("Voucher not found")

            total_debit = sum(e.get('debit', 0) for e in data['entries'])
            total_credit = sum(e.get('credit', 0) for e in data['entries'])
            # Same one-sided exception as create — see _create_voucher_internal.
            if len(data['entries']) > 1 and abs(total_debit - total_credit) > 0.01:
                raise ValueError(f"Debit ({total_debit}) != Credit ({total_credit})")

            conn.execute("""
                UPDATE vouchers
                SET date=?, reference=?, narration=?
                WHERE id=?
            """, (
                data['date'],
                data.get('reference', ''),
                data.get('narration', ''),
                voucher_id
            ))

            # Old entries hata kar naye entries daalo (simple replace strategy)
            conn.execute("DELETE FROM voucher_entries WHERE voucher_id=?", (voucher_id,))
            for entry in data['entries']:
                conn.execute("""
                    INSERT INTO voucher_entries (voucher_id, ledger_id, debit, credit)
                    VALUES (?, ?, ?, ?)
                """, (voucher_id, entry['ledger_id'], entry.get('debit', 0), entry.get('credit', 0)))

            conn.commit()
            return {"voucher_id": voucher_id, "voucher_number": existing['voucher_number']}

    @staticmethod
    def delete_voucher(voucher_id: int, force=False) -> bool:
        with get_conn() as conn:
            v = conn.execute("SELECT is_posted FROM vouchers WHERE id=?", (voucher_id,)).fetchone()
            if not v:
                return False
            if v['is_posted'] and not force:
                return False
            conn.execute("DELETE FROM vouchers WHERE id=?", (voucher_id,))
            conn.commit()
            return True

    @staticmethod
    def _get_net_profit_loss(as_on_date: str = None) -> float:
        with get_conn() as conn:
            income_groups = conn.execute("SELECT id FROM account_groups WHERE group_type IN ('Income', 'Revenue')").fetchall()
            expense_groups = conn.execute("SELECT id FROM account_groups WHERE group_type IN ('Expense', 'Cost')").fetchall()
            total_income = 0.0
            total_expenses = 0.0

            for gid in income_groups:
                query = """
                    SELECT COALESCE(SUM(ve.credit) - SUM(ve.debit), 0) as balance
                    FROM ledgers l
                    LEFT JOIN voucher_entries ve ON ve.ledger_id = l.id
                    LEFT JOIN vouchers v ON v.id = ve.voucher_id
                    WHERE l.group_id = ?
                """
                params = [gid['id']]
                if as_on_date:
                    query += " AND v.date <= ?"
                    params.append(as_on_date)
                result = conn.execute(query, params).fetchone()
                total_income += result['balance'] if result else 0.0

            for gid in expense_groups:
                query = """
                    SELECT COALESCE(SUM(ve.debit) - SUM(ve.credit), 0) as balance
                    FROM ledgers l
                    LEFT JOIN voucher_entries ve ON ve.ledger_id = l.id
                    LEFT JOIN vouchers v ON v.id = ve.voucher_id
                    WHERE l.group_id = ?
                """
                params = [gid['id']]
                if as_on_date:
                    query += " AND v.date <= ?"
                    params.append(as_on_date)
                result = conn.execute(query, params).fetchone()
                total_expenses += result['balance'] if result else 0.0

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
        # SQL aggregate instead of pulling every purchase_items row into
        # Python and summing in a loop (was O(rows); at 1 lakh+ rows this
        # alone added real time to every call, including from get_profit_loss()
        # which dashboard's KPI card calls).
        row = conn.execute("""
            SELECT COALESCE(SUM(
                CASE WHEN qty > 0 AND (qty - sold) > 0
                     THEN buy_total * (qty - sold) * 1.0 / qty ELSE 0 END
            ), 0) as total
            FROM purchase_items
        """).fetchone()
        return row['total'] or 0.0

    @staticmethod
    def get_balance_sheet(as_on_date: str = None) -> Dict:
        with get_conn() as conn:
            groups = conn.execute("SELECT * FROM account_groups").fetchall()
            ledgers = conn.execute("SELECT * FROM ledgers WHERE is_active=1").fetchall()
            assets = []
            liabilities = []
            equity = []

            for ledger in ledgers:
                bal = VoucherEngine._get_ledger_balance(ledger['id'], as_on_date, conn)
                entry = {
                    "ledger": ledger['name'],
                    "group": VoucherEngine._get_group_name(ledger['group_id'], conn),
                    "balance": abs(bal['balance']),
                    "balance_type": bal['balance_type']
                }
                group = next((g for g in groups if g['id'] == ledger['group_id']), None)
                if group:
                    if group['group_type'] == 'Assets':
                        assets.append(entry)
                    elif group['group_type'] == 'Liabilities':
                        liabilities.append(entry)
                    elif group['group_type'] == 'Equity':
                        equity.append(entry)
                else:
                    liabilities.append(entry)

            stock_value = VoucherEngine.get_stock_value(conn)
            if stock_value > 0:
                assets.append({
                    "ledger": "Stock-in-Hand",
                    "group": "Current Assets",
                    "balance": stock_value,
                    "balance_type": "Debit"
                })

            net_profit = VoucherEngine._get_net_profit_loss(as_on_date)
            if abs(net_profit) > 0.001:
                if net_profit > 0:
                    equity.append({
                        "ledger": "Net Profit",
                        "group": "Equity",
                        "balance": net_profit,
                        "balance_type": "Credit"
                    })
                else:
                    equity.append({
                        "ledger": "Net Loss",
                        "group": "Equity",
                        "balance": abs(net_profit),
                        "balance_type": "Debit"
                    })

            total_assets = sum(a['balance'] for a in assets)
            total_liabilities = sum(l['balance'] for l in liabilities)
            total_equity = sum(e['balance'] if e['balance_type'] == 'Credit' else -e['balance'] for e in equity)

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
        with get_conn() as conn:
            ledgers = conn.execute("SELECT * FROM ledgers WHERE is_active=1").fetchall()
            result = []
            for ledger in ledgers:
                balance = VoucherEngine._get_ledger_balance(ledger['id'], as_on_date, conn)
                result.append({
                    "ledger_name": ledger['name'],
                    "group_name": VoucherEngine._get_group_name(ledger['group_id'], conn),
                    "debit": balance['balance'] if balance['balance_type'] == 'Debit' else 0,
                    "credit": balance['balance'] if balance['balance_type'] == 'Credit' else 0,
                })
            return result

    @staticmethod
    def get_profit_loss(from_date: str, to_date: str, closing_stock: float = None) -> Dict:
        with get_conn() as conn:
            income_groups = conn.execute("SELECT id FROM account_groups WHERE group_type IN ('Income', 'Revenue')").fetchall()
            expense_groups = conn.execute("SELECT id FROM account_groups WHERE group_type IN ('Expense', 'Cost')").fetchall()
            income = []
            for gid in income_groups:
                rows = conn.execute("""
                    SELECT l.name as ledger_name,
                           COALESCE(SUM(ve.credit) - SUM(ve.debit), 0) as balance
                    FROM ledgers l
                    LEFT JOIN voucher_entries ve ON ve.ledger_id = l.id
                    LEFT JOIN vouchers v ON v.id = ve.voucher_id
                    WHERE l.group_id = ? AND v.date BETWEEN ? AND ?
                    GROUP BY l.id
                    HAVING balance > 0
                """, (gid['id'], from_date, to_date)).fetchall()
                income.extend([dict(r) for r in rows])

            # Caller (dashboard) usually already has this number from its own
            # purchase_items aggregate -- only recompute (another full-table
            # scan over purchase_items) if it wasn't handed to us.
            if closing_stock is None:
                closing_stock = VoucherEngine.get_stock_value(conn)
            if closing_stock > 0:
                income.append({"ledger_name": "Closing Stock", "balance": closing_stock})

            expenses = []
            for gid in expense_groups:
                rows = conn.execute("""
                    SELECT l.name as ledger_name,
                           COALESCE(SUM(ve.debit) - SUM(ve.credit), 0) as balance
                    FROM ledgers l
                    LEFT JOIN voucher_entries ve ON ve.ledger_id = l.id
                    LEFT JOIN vouchers v ON v.id = ve.voucher_id
                    WHERE l.group_id = ? AND v.date BETWEEN ? AND ?
                    GROUP BY l.id
                    HAVING balance > 0
                """, (gid['id'], from_date, to_date)).fetchall()
                expenses.extend([dict(r) for r in rows])
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
                SELECT v.date, v.voucher_number, v.voucher_type, v.narration,
                       ve.debit, ve.credit, l.name as ledger_name
                FROM voucher_entries ve
                JOIN vouchers v ON v.id = ve.voucher_id
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
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT v.id, v.voucher_number, v.voucher_type, v.date,
                       v.reference, v.narration,
                       (SELECT l.name FROM ledgers l
                        JOIN voucher_entries ve ON ve.ledger_id = l.id
                        WHERE ve.voucher_id = v.id
                        AND (l.group_id IN (SELECT id FROM account_groups WHERE name IN ('Sundry Debtors', 'Sundry Creditors')))
                        LIMIT 1) as party_name,
                        (SELECT MAX(COALESCE(SUM(debit),0), COALESCE(SUM(credit),0)) FROM voucher_entries WHERE voucher_id = v.id) as amount
                FROM vouchers v
                WHERE date(v.date) = date(?)
                ORDER BY v.id
            """, (date_str,)).fetchall()
            return [dict(r) for r in rows]
