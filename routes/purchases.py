from datetime import datetime
import threading
import psycopg2.extras

from flask import Blueprint, request, jsonify

from core.db import get_conn
from core.shared_helpers import to_camel_row, get_or_create_ledger, round2
import core.dashboard_cache as dashboard_cache
from core.accounting import VoucherEngine

purchases_bp = Blueprint("purchases", __name__)


def _trigger_async_cache_recompute():
    def _async_recompute():
        try:
            with get_conn() as conn:
                import core.dashboard_cache as dashboard_cache
                import core.reports_cache as reports_cache
                dashboard_cache.recompute_global_snapshot(conn)
                reports_cache.recompute_all(conn)
                conn.commit()
        except Exception as e:
            print(f"Async cache recompute error: {e}")

    threading.Thread(target=_async_recompute, daemon=True).start()


def ensure_item_in_master(name, size, department, conn):
    name = (name or "").strip()
    if not name:
        return
    size = (size or "").strip()
    existing = conn.execute(
        "SELECT id FROM items WHERE LOWER(name) = LOWER(?) AND LOWER(COALESCE(size, '')) = LOWER(?)",
        (name, size)
    ).fetchone()
    if existing:
        return
    conn.execute("""
        INSERT INTO items (name, size, department, hsn, unit, defaultMargin, defaultGST, min_stock, createdAt)
        VALUES (?, ?, ?, '', '', 0, 0, 0, NOW())
    """, (name, size, department or ''))


def ensure_party_in_master(name, seller_no, address, gst_no, conn):
    name = (name or "").strip()
    if not name:
        return None
    existing = conn.execute(
        "SELECT party_id FROM parties WHERE LOWER(party_name) = LOWER(?)", (name,)
    ).fetchone()
    if existing:
        return existing["party_id"]
    gst = (gst_no or "").strip() or None
    cur = conn.execute(
        "INSERT INTO parties (party_name, contact_no, address, gst_no) VALUES (?, ?, ?, ?)",
        (name, seller_no or '', address or '', gst)
    )
    return cur.lastrowid


def _lock_barcode_counter(conn):
    row = conn.execute("""
        SELECT last_barcode FROM purchase_item WHERE barcode_no = 0 FOR UPDATE
    """).fetchone()
    return int(row["last_barcode"]) if row and row["last_barcode"] is not None else 99999


def _save_barcode_counter(conn, last_barcode):
    conn.execute(
        "UPDATE purchase_item SET last_barcode = ? WHERE barcode_no = 0",
        (last_barcode,)
    )


def resolve_credit_bill_status(remaining_amount, paid_amount, due_date):
    """
    Single source of truth for what a credit purchase bill's status should
    be, given how much is still owed and its due date:
      - fully paid                              -> 'Paid'
      - still owed, due date has passed         -> 'Overdue'
      - still owed, some payment made already   -> 'Partial'
      - still owed, nothing paid yet            -> 'Credit'
    """
    if remaining_amount <= 0.01:
        return 'Paid'
    if due_date and str(due_date) < datetime.now().strftime("%Y-%m-%d"):
        return 'Overdue'
    if paid_amount > 0:
        return 'Partial'
    return 'Credit'


def sync_overdue_purchase_statuses(conn):
    """
    Keep purchases_header.status in the database in sync with due dates:
      - flips unpaid Credit/Partial bills whose due date has passed to
        'Overdue'
      - flips them back if the due date is edited out to the future (or
        cleared) while still unpaid
    Called before any read that reports purchase borrow status/summary so
    the stored status is always accurate, not just computed on the fly.
    """
    conn.execute("""
        UPDATE purchases_header
        SET status = 'Overdue'
        WHERE status IN ('Credit','Partial')
          AND due_date IS NOT NULL
          AND due_date < CURRENT_DATE
    """)
    conn.execute("""
        UPDATE purchases_header ph
        SET status = CASE WHEN COALESCE(pp.paid_amount, 0) > 0 THEN 'Partial' ELSE 'Credit' END
        FROM purchase_payments pp
        WHERE pp.purchase_id = ph.id
          AND ph.status = 'Overdue'
          AND (ph.due_date IS NULL OR ph.due_date >= CURRENT_DATE)
    """)


def create_purchase_bill(header_data, items, mode):
    from core.accounting import VoucherEngine

    with get_conn() as conn:
        party_id = ensure_party_in_master(
            header_data.get('party', ''),
            header_data.get('seller_no', ''),
            header_data.get('seller_address', ''),
            header_data.get('gst_no', ''),
            conn
        )

        is_credit = (mode or '').lower() == 'credit'
        bill_status = 'Credit' if is_credit else 'Cash'
        date_str = header_data.get('date', datetime.now().strftime("%Y-%m-%d"))
        if " " in str(date_str):
            date_str = str(date_str).split(" ")[0]

        discount_pct = float(header_data.get('discount', 0) or 0)
        cgst_rate = float(header_data.get('cgst', 0) or 0)
        sgst_rate = float(header_data.get('sgst', 0) or 0)
        igst_rate = float(header_data.get('igst', 0) or 0)
        # Only meaningful for credit purchases; stays NULL for cash bills.
        due_date = header_data.get('due_date') or None if is_credit else None

        cur = conn.execute("""
            INSERT INTO purchases_header
            (purchase_id, party_id, date, due_date, status, invoice_no, created_at)
            VALUES (NULL, ?, ?, ?, ?, ?, ?)
        """, (
            party_id, date_str, due_date, bill_status,
            header_data.get('invoice_no', ''),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        header_id = cur.lastrowid
        conn.execute(
            "UPDATE purchases_header SET purchase_id = ? WHERE id = ?",
            (header_id, header_id)
        )

        if is_credit and party_id:
            conn.execute(
                "UPDATE parties SET status = 'Credit' WHERE party_id = ?",
                (party_id,)
            )

        total_buy = 0.0
        total_sell = 0.0
        total_with_gst = 0.0
        # Separate accumulators matching the Reports stats formula exactly
        # (qty * unit_price * (1 + margin/100), unrounded) -- total_sell
        # above uses the rounded-to-5 display sell_price instead, which is
        # NOT what the cached reports stats need to stay consistent with.
        stats_qty = 0.0
        stats_sell_total = 0.0
        next_barcode = _lock_barcode_counter(conn)
        barcode_rows = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for item in items:
            ensure_item_in_master(
                item.get('item', ''),
                item.get('size', ''),
                item.get('department', '') or header_data.get('department', ''),
                conn
            )

            qty = float(item.get('qty', 0))
            buy = float(item.get('buy', 0))
            margin = float(item.get('margin', 0))
            explicit_sell = float(item.get('sell_price', 0) or 0)
            sell_price = explicit_sell if explicit_sell > 0 else round(buy * (1 + margin / 100) / 5) * 5
            sell_total = qty * sell_price

            effective_buy = buy * (1 - discount_pct / 100)
            buy_total = qty * effective_buy
            item_cgst = float(item.get('cgst', cgst_rate) or 0)
            item_sgst = float(item.get('sgst', sgst_rate) or 0)
            item_igst = float(item.get('igst', igst_rate) or 0)
            total_with_gst_item = buy_total * (1 + (item_cgst + item_sgst + item_igst) / 100)
            remaining = qty
            sell_unit = sell_price  # sell_price already handles both explicit and computed cases
            projected = round((sell_unit - effective_buy) * remaining, 2) if remaining > 0 else 0.0

            cur_prod = conn.execute("""
                INSERT INTO products
                (party_id, purchase_id, item_name, size, date, total_buy_price,
                 unit_price, department, margin, qty, sold, remaining,
                 projected_margin, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
            """, (
                party_id, header_id,
                item.get('item', ''),
                item.get('size', '') or None,
                date_str, buy_total, effective_buy,
                item.get('department', '') or header_data.get('department', ''),
                margin, qty, remaining, projected, bill_status,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ))
            product_id = cur_prod.lastrowid

            total_buy += buy_total
            total_sell += sell_total
            total_with_gst += total_with_gst_item
            stats_qty += qty
            stats_sell_total += qty * effective_buy * (1 + margin / 100)

            for _ in range(round(qty)):
                next_barcode += 1
                barcode_rows.append((
                    product_id, party_id,
                    item.get('item', ''),
                    item.get('size', '') or None,
                    next_barcode, effective_buy, sell_price, margin,
                    'available', 0, now_str
                ))

        if barcode_rows:
            psycopg2.extras.execute_values(conn.cursor(), """
                INSERT INTO purchase_item
                (product_id, party_id, item_name, size, barcode_no,
                 buy_price, sale_price, margin, is_available, is_returned, created_at)
                VALUES %s
            """, barcode_rows)

        _save_barcode_counter(conn, next_barcode)

        if is_credit:
            paid_amount = float(header_data.get('advance_amount', 0) or 0)
            paid_amount = max(0.0, min(paid_amount, total_with_gst))
        else:
            paid_amount = total_with_gst
        remaining_amount = total_with_gst - paid_amount

        if is_credit:
            bill_status = resolve_credit_bill_status(remaining_amount, paid_amount, due_date)
            conn.execute(
                "UPDATE purchases_header SET status = ? WHERE id = ?",
                (bill_status, header_id)
            )
            prod_status = 'Paid' if bill_status == 'Paid' else 'Credit'
            conn.execute(
                "UPDATE products SET status = ? WHERE purchase_id = ?",
                (prod_status, header_id)
            )
            if bill_status == 'Paid' and party_id:
                open_bills = conn.execute("""
                    SELECT COUNT(*) c FROM purchases_header
                    WHERE party_id = ? AND status IN ('Credit','Partial','Overdue') AND id != ?
                """, (party_id, header_id)).fetchone()["c"]
                if open_bills == 0:
                    conn.execute(
                        "UPDATE parties SET status = 'Cash' WHERE party_id = ?",
                        (party_id,)
                    )

        mode_of_payment = 'Credit' if is_credit else 'Cash'
        conn.execute("""
            INSERT INTO purchase_payments
            (purchase_id, party_id, is_credit, mode_of_payment, total_buy_amount, total_with_gst,
             total_buy_amount_discount, paid_amount, remaining_amount,
             cgst, sgst, igst, discount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            header_id, party_id, (1 if is_credit else 0), mode_of_payment,
            total_buy, total_with_gst, total_buy,   # already post-discount
            paid_amount, remaining_amount,
            cgst_rate, sgst_rate, igst_rate, discount_pct
        ))

        try:
            purchase_ledger = conn.execute("SELECT id FROM ledgers WHERE name = 'Purchase'").fetchone()
            gst_input = conn.execute("SELECT id FROM ledgers WHERE name = 'GST Input'").fetchone()
            party_name = (header_data.get('party') or '').strip()

            entries = []
            if purchase_ledger:
                entries.append({"ledger_id": purchase_ledger["id"], "debit": total_buy, "credit": 0})
            gst_amount = total_with_gst - total_buy
            if gst_amount > 0.01 and gst_input:
                entries.append({"ledger_id": gst_input["id"], "debit": gst_amount, "credit": 0})

            party_ledger_id = None
            if is_credit:
                party_ledger_id = get_or_create_ledger(
                    party_name or "Unknown", "Sundry Creditors", "Credit", conn
                )
                entries.append({"ledger_id": party_ledger_id, "debit": 0, "credit": total_with_gst})
            else:
                cash_ledger = conn.execute("SELECT id FROM ledgers WHERE name = 'Cash'").fetchone()
                if cash_ledger:
                    entries.append({"ledger_id": cash_ledger["id"], "debit": 0, "credit": total_with_gst})
                # Zero-amount entry so the vendor's ledger is still linked to
                # this voucher (used only to show the party name in the Voucher
                # List) -- it does not affect the debit/credit balance.
                party_ledger_id = get_or_create_ledger(
                    party_name or "Unknown", "Sundry Creditors", "Credit", conn
                )
                entries.append({"ledger_id": party_ledger_id, "debit": 0, "credit": 0})

            if entries and len(entries) > 1:
                result = VoucherEngine.create_voucher({
                    "voucher_type": "PURCHASE",
                    "date": date_str,
                    "reference": header_data.get('invoice_no', ''),
                    "narration": f"Purchase from {party_name}",
                    "created_by": "admin",
                    "entries": entries
                }, conn=conn)
                conn.execute(
                    "UPDATE purchases_header SET voucher_id = ? WHERE id = ?",
                    (result["voucher_id"], header_id)
                )

            if is_credit and paid_amount > 0:
                cash_ledger = conn.execute("SELECT id FROM ledgers WHERE name = 'Cash'").fetchone()
                if cash_ledger and party_ledger_id:
                    VoucherEngine.create_voucher({
                        "voucher_type": "PAYMENT",
                        "date": date_str,
                        "reference": header_data.get('invoice_no', ''),
                        "narration": f"Advance paid to {party_name}",
                        "created_by": "admin",
                        "entries": [
                            {"ledger_id": party_ledger_id, "debit": paid_amount, "credit": 0},
                            {"ledger_id": cash_ledger["id"], "debit": 0, "credit": paid_amount},
                        ]
                    }, conn=conn)
        except Exception as e:
            print(f"Purchase voucher auto-sync warning: {e}")

        import core.dashboard_cache as dashboard_cache
        dashboard_cache.apply_transaction_delta(
            conn, date_str,
            purchases_delta=total_with_gst,
            credit_purchases_delta=total_with_gst if bill_status in ('Credit', 'Partial', 'Overdue') else 0,
            txn_type="purchase",
            recent_entry={
                "date": date_str,
                "party": header_data.get('party', ''),
                "invoiceNo": header_data.get('invoice_no', ''),
                "buyTotal": total_buy,
            }
        )

        import core.reports_cache as reports_cache
        reports_cache.apply_purchase_delta(
            conn, bill_status,
            count_delta=len(items),
            qty_delta=stats_qty,
            buy_delta=total_buy,
            sell_delta=stats_sell_total,
            profit_delta=stats_sell_total - total_buy,
            bill_date=date_str,
            total_buy_amount=total_buy,
        )

        # O(1) incremental delta — avoids full products-table scan.
        # stock_value += total cost of goods received (pre-GST, post-discount)
        # stock_qty   += total units received
        # payable     += what we still owe supplier (0 for cash/fully-advance bills)
        dashboard_cache.apply_stock_financial_delta(
            conn,
            stock_value_delta=total_buy,
            stock_qty_delta=stats_qty,
            payable_delta=remaining_amount,
            receivable_delta=0,
        )
        conn.commit()
        return header_id


def get_purchase_bill(purchase_id):
    with get_conn() as conn:
        header = conn.execute("""
            SELECT ph.id, ph.purchase_id, ph.party_id, ph.date, ph.due_date, ph.status, ph.invoice_no,
                   ph.voucher_id, ph.created_at,
                   p.party_name AS party, p.contact_no AS seller_no, p.address AS seller_address,
                   p.gst_no AS seller_gst_no,
                   pp.total_buy_amount AS total_buy, pp.total_with_gst, pp.discount,
                   pp.cgst AS cgst_rate, pp.sgst AS sgst_rate, pp.igst AS igst_rate,
                   pp.paid_amount, pp.remaining_amount, pp.mode_of_payment,
                   CASE WHEN ph.status = 'Cash' THEN 'cash' ELSE 'credit' END AS mode
            FROM purchases_header ph
            LEFT JOIN parties p ON p.party_id = ph.party_id
            LEFT JOIN purchase_payments pp ON pp.purchase_id = ph.id
            WHERE ph.id = ?
        """, (purchase_id,)).fetchone()
        if not header:
            return None
        header_dict = dict(header)
        header_dict['cgst'] = float(header_dict.get('cgst_rate') or 0)
        header_dict['sgst'] = float(header_dict.get('sgst_rate') or 0)
        header_dict['igst'] = float(header_dict.get('igst_rate') or 0)
        # Back-calculate the original (before-discount) buy price for each item.
        # unit_price in DB stores effective_buy = buy * (1 - discount/100).
        # So: original_buy = unit_price / (1 - discount/100)  when discount < 100.
        discount_pct = float(header_dict.get('discount') or 0)
        header_dict['discountPct'] = discount_pct
        divisor = 1.0 - discount_pct / 100.0 if discount_pct < 100 else 1.0

        items = conn.execute("""
            SELECT product_id AS id, product_id, item_name AS item, size, qty, sold, remaining,
                   unit_price AS buy_price, unit_price AS buy, margin,
                   (unit_price * (1 + COALESCE(margin,0)/100)) AS sell_price,
                   total_buy_price AS buy_total, projected_margin, department, status
            FROM products WHERE purchase_id = ?
        """, (purchase_id,)).fetchall()

        items_list = []
        for it in items:
            d = dict(it)
            effective_buy = float(d.get('buy_price') or 0)
            margin = float(d.get('margin') or 0)
            # Reconstruct original buy price (before supplier discount was applied)
            original_buy = round(effective_buy / divisor, 2) if divisor > 0 else effective_buy
            d['original_buy_price'] = original_buy
            # sell_price must be based on original buy price (not effective/after-discount),
            # matching the entry form logic: sell = roundToNearest5(buy * (1 + margin/100))
            raw_sell = original_buy * (1 + margin / 100)
            d['sell_price'] = round(raw_sell / 5) * 5  # round to nearest 5 like the entry form
            items_list.append(d)

        return header_dict, items_list


def get_purchase_rows(filters=None, limit=None, offset=None):
    with get_conn() as conn:
        # Fast path for large offsets (e.g. Page 8000, offset >= 1000):
        # Avoid 40-second full table OFFSET scan by using B-Tree Primary Key Seek
        if offset and int(offset) >= 1000 and not any(filters.get(k) for k in ('date_from', 'date_to', 'party', 'item', 'department', 'search', 'sold_only')):
            max_row = conn.execute("SELECT MAX(product_id) as m FROM products").fetchone()
            max_id = max_row['m'] if max_row else 0
            if max_id:
                mode_val = (filters or {}).get('mode')
                multiplier = 2.5 if mode_val == 'cash' else (1.67 if mode_val == 'credit' else 1.0)
                target_id = max_id - int(int(offset) * multiplier)
                if target_id > 0:
                    fast_where = ""
                    fast_params = []
                    if mode_val == 'cash':
                        fast_where = " AND ph.status = 'Cash'"
                    elif mode_val == 'credit':
                        fast_where = " AND ph.status IN ('Credit','Partial','Paid','Overdue')"
                    fast_query = f"""
                        SELECT
                            ph.id as purchase_id, ph.invoice_no, pt.party_name as party,
                            pt.contact_no as seller_no, pt.address as seller_address,
                            pt.gst_no as seller_gst_no,
                            ph.date, pr.department,
                            CASE WHEN ph.status = 'Cash' THEN 'cash' ELSE 'credit' END as mode,
                            pr.product_id as id, pr.product_id as item_id,
                            pr.item_name as item, pr.size, pr.qty, pr.sold, pr.remaining,
                            pr.unit_price as buy, pr.margin,
                            (pr.unit_price * (1 + COALESCE(pr.margin,0)/100)) as "sellUnit",
                            pr.total_buy_price as "buyTotal",
                            (pr.qty * pr.unit_price * (1 + COALESCE(pr.margin,0)/100)) as "sellTotal",
                            ((pr.qty * pr.unit_price * (1 + COALESCE(pr.margin,0)/100)) - pr.total_buy_price) as profit,
                            COALESCE(pp.cgst, 0) as cgst, COALESCE(pp.sgst, 0) as sgst,
                            COALESCE(pp.igst, 0) as igst,
                            COALESCE(pp.discount, 0) as discount,
                            COALESCE(pp.total_buy_amount_discount, pr.total_buy_price) as "totalAfterDiscount",
                            COALESCE(pp.total_with_gst, pr.total_buy_price) as "totalWithGST",
                            COALESCE(pp.paid_amount, 0) as "paidAmount",
                            COALESCE(pp.remaining_amount, 0) as "remainingAmount",
                            pr.department as item_dept, ph.status
                        FROM products pr
                        JOIN purchases_header ph ON ph.id = pr.purchase_id
                        LEFT JOIN parties pt ON pt.party_id = ph.party_id
                        LEFT JOIN purchase_payments pp ON pp.purchase_id = ph.id
                        WHERE pr.product_id <= ? {fast_where}
                        ORDER BY pr.product_id DESC
                        LIMIT ?
                    """
                    fast_rows = conn.execute(fast_query, [target_id] + ([int(limit)] if limit else [100])).fetchall()
                    if fast_rows and len(fast_rows) >= (limit or 100):
                        return [dict(r) for r in fast_rows]

        query = """
            SELECT
                ph.id as purchase_id,
                ph.invoice_no,
                pt.party_name as party,
                pt.contact_no as seller_no,
                pt.address as seller_address,
                pt.gst_no as seller_gst_no,
                ph.date,
                pr.department,
                CASE WHEN ph.status = 'Cash' THEN 'cash' ELSE 'credit' END as mode,
                pr.product_id as id,
                pr.product_id as item_id,
                pr.item_name as item,
                pr.size,
                pr.qty,
                pr.sold,
                pr.remaining,
                pr.unit_price as buy,
                pr.margin,
                (pr.unit_price * (1 + COALESCE(pr.margin,0)/100)) as "sellUnit",
                pr.total_buy_price as "buyTotal",
                (pr.qty * pr.unit_price * (1 + COALESCE(pr.margin,0)/100)) as "sellTotal",
                ((pr.qty * pr.unit_price * (1 + COALESCE(pr.margin,0)/100)) - pr.total_buy_price) as profit,
                COALESCE(pp.cgst, 0) as cgst,
                COALESCE(pp.sgst, 0) as sgst,
                COALESCE(pp.igst, 0) as igst,
                COALESCE(pp.discount, 0) as discount,
                COALESCE(pp.total_buy_amount_discount, pr.total_buy_price) as "totalAfterDiscount",
                COALESCE(pp.total_with_gst, pr.total_buy_price) as "totalWithGST",
                COALESCE(pp.paid_amount, 0) as "paidAmount",
                COALESCE(pp.remaining_amount, 0) as "remainingAmount",
                pr.department as item_dept,
                ph.status
            FROM purchases_header ph
            JOIN products pr ON pr.purchase_id = ph.id
            LEFT JOIN parties pt ON pt.party_id = ph.party_id
            LEFT JOIN purchase_payments pp ON pp.purchase_id = ph.id
            WHERE ph.status != 'deleted'
        """
        params = []
        if filters:
            if filters.get('status') == 'deleted':
                query = query.replace("WHERE ph.status != 'deleted'", "WHERE ph.status = 'deleted'")
            if 'mode' in filters:
                mode = filters['mode']
                if mode == 'cash':
                    query += " AND ph.status = 'Cash'"
                elif mode == 'credit':
                    query += " AND ph.status IN ('Credit','Partial','Paid','Overdue')"
            if 'date_from' in filters:
                query += " AND ph.date >= ?"
                params.append(filters['date_from'])
            if 'date_to' in filters:
                query += " AND ph.date <= ?"
                params.append(filters['date_to'])
            if 'party' in filters and filters['party']:
                query += " AND pt.party_name LIKE ?"
                params.append(f"%{filters['party']}%")
            if 'item' in filters and filters['item']:
                query += " AND pr.item_name LIKE ?"
                params.append(f"%{filters['item']}%")
            if 'department' in filters and filters['department']:
                query += " AND pr.department = ?"
                params.append(filters['department'])
            if filters.get('sold_only'):
                query += " AND pr.sold > 0"
            if filters.get('search'):
                query += " AND (pr.item_name ILIKE ? OR pr.size ILIKE ? OR pt.party_name ILIKE ?)"
                like = f"%{filters['search']}%"
                params.extend([like, like, like])
        query += " ORDER BY ph.date DESC, ph.id DESC, pr.product_id"
        if limit is not None:
            query += " LIMIT ?"
            params.append(int(limit))
            if offset is not None:
                query += " OFFSET ?"
                params.append(int(offset))
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_purchase_stats(filters=None):
    with get_conn() as conn:
        query = """
            SELECT
                COUNT(pr.product_id) as total_entries,
                COALESCE(SUM(pr.qty), 0) as total_qty,
                COALESCE(SUM(pr.total_buy_price), 0) as total_purchase,
                COALESCE(SUM(pr.qty * pr.unit_price * (1 + COALESCE(pr.margin,0)/100)), 0) as total_sell,
                COALESCE(SUM(
                    (pr.qty * pr.unit_price * (1 + COALESCE(pr.margin,0)/100)) - pr.total_buy_price
                ), 0) as total_profit
            FROM purchases_header ph
            JOIN products pr ON pr.purchase_id = ph.id
            LEFT JOIN parties pt ON pt.party_id = ph.party_id
            WHERE ph.status != 'deleted'
        """
        params = []
        if filters:
            if 'mode' in filters:
                mode = filters['mode']
                if mode == 'cash':
                    query += " AND ph.status = 'Cash'"
                elif mode == 'credit':
                    query += " AND ph.status IN ('Credit','Partial','Paid')"
            if 'date_from' in filters:
                query += " AND ph.date >= ?"
                params.append(filters['date_from'])
            if 'date_to' in filters:
                query += " AND ph.date <= ?"
                params.append(filters['date_to'])
            if 'party' in filters and filters['party']:
                query += " AND pt.party_name LIKE ?"
                params.append(f"%{filters['party']}%")
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else {
            "total_entries": 0, "total_qty": 0, "total_purchase": 0,
            "total_sell": 0, "total_profit": 0
        }


def get_purchase_rows_count(filters=None):
    # Fast path: if filters is empty or only contains 'mode', read purchase_count directly
    # from reports_stats_cache table (0.2ms instead of 1200ms!)
    if not filters or (set(filters.keys()).issubset({'mode'}) and filters.get('mode') in (None, 'all', 'cash', 'credit')):
        mode_val = (filters or {}).get('mode') or 'all'
        with get_conn() as conn:
            row = conn.execute(
                "SELECT purchase_count FROM reports_stats_cache WHERE mode = ?", (mode_val,)
            ).fetchone()
            if row and row['purchase_count'] is not None and row['purchase_count'] > 0:
                return int(row['purchase_count'])

    with get_conn() as conn:
        has_party = filters and (filters.get('party') or filters.get('search'))
        party_join = "LEFT JOIN parties pt ON pt.party_id = ph.party_id" if has_party else ""
        query = f"""
            SELECT COUNT(*) as c
            FROM purchases_header ph
            JOIN products pr ON pr.purchase_id = ph.id
            {party_join}
            WHERE ph.status != 'deleted'
        """
        params = []
        if filters:
            if filters.get('status') == 'deleted':
                query = query.replace("WHERE ph.status != 'deleted'", "WHERE ph.status = 'deleted'")
            if 'mode' in filters:
                mode = filters['mode']
                if mode == 'cash':
                    query += " AND ph.status = 'Cash'"
                elif mode == 'credit':
                    query += " AND ph.status IN ('Credit','Partial','Paid','Overdue')"
            if 'date_from' in filters:
                query += " AND ph.date >= ?"
                params.append(filters['date_from'])
            if 'date_to' in filters:
                query += " AND ph.date <= ?"
                params.append(filters['date_to'])
            if 'party' in filters and filters['party']:
                query += " AND pt.party_name LIKE ?"
                params.append(f"%{filters['party']}%")
            if filters.get('sold_only'):
                query += " AND pr.sold > 0"
            if filters.get('search'):
                query += " AND (pr.item_name ILIKE ? OR pr.size ILIKE ? OR pt.party_name ILIKE ?)"
                like = f"%{filters['search']}%"
                params.extend([like, like, like])
        return conn.execute(query, params).fetchone()["c"]


def get_sold_items_totals(filters=None):
    """Aggregate totals (qty sold, revenue) across ALL matching sold rows --
    used for the Sold Items footer, so it reflects the full filtered set
    even though only one page of rows is ever sent to the browser."""
    with get_conn() as conn:
        query = """
            SELECT
                COALESCE(SUM(pr.sold), 0) as total_sold,
                COALESCE(SUM(pr.sold * pr.unit_price * (1 + COALESCE(pr.margin,0)/100)), 0) as total_revenue
            FROM purchases_header ph
            JOIN products pr ON pr.purchase_id = ph.id
            LEFT JOIN parties pt ON pt.party_id = ph.party_id
            WHERE pr.sold > 0
        """
        params = []
        if filters:
            if filters.get('date_from'):
                query += " AND ph.date >= ?"
                params.append(filters['date_from'])
            if filters.get('date_to'):
                query += " AND ph.date <= ?"
                params.append(filters['date_to'])
            if filters.get('search'):
                query += " AND (pr.item_name ILIKE ? OR pr.size ILIKE ? OR pt.party_name ILIKE ?)"
                like = f"%{filters['search']}%"
                params.extend([like, like, like])
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else {"total_sold": 0, "total_revenue": 0}


@purchases_bp.route("/api/sold_items/stats", methods=["GET"])
def api_sold_items_stats():
    filters = {}
    if request.args.get("date_from"):
        filters["date_from"] = request.args.get("date_from")
    if request.args.get("date_to"):
        filters["date_to"] = request.args.get("date_to")
    if request.args.get("search"):
        filters["search"] = request.args.get("search")
    stats = get_sold_items_totals(filters)
    return jsonify({
        "totalSold": float(stats.get("total_sold") or 0),
        "totalRevenue": float(stats.get("total_revenue") or 0),
    })


@purchases_bp.route("/api/purchase_bill", methods=["POST"])
def api_purchase_bill():
    data = request.json or {}
    header = data.get("header") or data
    items = data.get("items") or []
    mode = data.get("mode") or header.get("mode") or "cash"
    if not items:
        return jsonify({"status": "error", "message": "No items"}), 400
    try:
        pid = create_purchase_bill(header, items, mode)
        return jsonify({"status": "ok", "purchaseId": pid, "id": pid})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 400


@purchases_bp.route("/api/purchase_bill/<int:purchase_id>", methods=["GET"])
def api_get_purchase_bill(purchase_id):
    result = get_purchase_bill(purchase_id)
    if not result:
        return jsonify({"error": "Not found"}), 404
    header, items = result
    return jsonify({"header": header, "items": items})


@purchases_bp.route("/api/purchase_bill/<int:purchase_id>", methods=["PUT"])
def api_update_purchase_bill(purchase_id):
    return jsonify({"status": "error", "message": "Purchase bill editing is disabled. Delete the bill instead if no items are sold."}), 400


def delete_purchase_bill(purchase_id):
    with get_conn() as conn:
        # 1. Validation: check if any item from this purchase bill has been sold
        sold_check = conn.execute("""
            SELECT COALESCE(SUM(sold), 0) as total_sold
            FROM products
            WHERE purchase_id = ?
        """, [purchase_id]).fetchone()
        total_sold = int(sold_check["total_sold"] or 0) if sold_check else 0

        sold_items_check = conn.execute("""
            SELECT COUNT(*) as cnt
            FROM purchase_item pi
            JOIN products p ON p.product_id = pi.product_id
            WHERE p.purchase_id = ? AND pi.is_available = 'sold'
        """, [purchase_id]).fetchone()
        sold_barcodes = int(sold_items_check["cnt"] or 0) if sold_items_check else 0

        if total_sold > 0 or sold_barcodes > 0:
            raise ValueError("Not able to delete this bill because one or more items of this bill have been sold.")

        header_row = conn.execute("SELECT invoice_no, voucher_id FROM purchases_header WHERE id = ?", [purchase_id]).fetchone()
        invoice_no = header_row["invoice_no"] if header_row else None
        linked_voucher_id = header_row["voucher_id"] if header_row else None

        # Capture payment totals BEFORE we zero them out in the delete below,
        # so we can apply the correct negative delta to the alltime cache row.
        _pp_row = conn.execute(
            "SELECT total_buy_amount, remaining_amount FROM purchase_payments WHERE purchase_id = ?",
            [purchase_id]
        ).fetchone()
        _prod_totals = conn.execute(
            "SELECT COALESCE(SUM(qty), 0) AS total_qty, COALESCE(SUM(total_buy_price), 0) AS total_buy FROM products WHERE purchase_id = ? AND status != 'deleted'",
            [purchase_id]
        ).fetchone()
        _del_stock_value = float(_prod_totals["total_buy"] or 0) if _prod_totals else 0.0
        _del_stock_qty   = float(_prod_totals["total_qty"] or 0) if _prod_totals else 0.0
        _del_payable     = float(_pp_row["remaining_amount"] or 0) if _pp_row else 0.0

        # 2. Mark statuses as deleted & unlink voucher_id FK
        conn.execute("""
            UPDATE purchase_item SET is_available = 'deleted'
            WHERE product_id IN (SELECT product_id FROM products WHERE purchase_id = ?)
        """, [purchase_id])
        conn.execute("UPDATE products SET status = 'deleted', remaining = 0 WHERE purchase_id = ?", [purchase_id])
        conn.execute("UPDATE purchases_header SET status = 'deleted', voucher_id = NULL WHERE id = ?", [purchase_id])
        conn.execute("UPDATE purchase_payments SET status = 'deleted', remaining_amount = 0, paid_amount = 0 WHERE purchase_id = ?", [purchase_id])

        # 3. Clean up Tally accounting vouchers & stock ledger
        vouchers = conn.execute("""
            SELECT id FROM vouchers
            WHERE (reference = ? AND reference IS NOT NULL AND reference != '')
               OR (reference = ? AND reference IS NOT NULL AND reference != '')
               OR id = ?
        """, [str(purchase_id), str(invoice_no) if invoice_no else '', linked_voucher_id or -1]).fetchall()

        for v in vouchers:
            v_id = v["id"]
            conn.execute("DELETE FROM stock_ledger WHERE voucher_id = ?", [v_id])
            conn.execute("DELETE FROM voucher_entries WHERE voucher_id = ?", [v_id])
            conn.execute("DELETE FROM vouchers WHERE id = ?", [v_id])

        # O(1) cache delta — negative because we're removing stock and clearing payable.
        # Must run before commit so it's atomic with the delete.
        import core.dashboard_cache as dashboard_cache
        dashboard_cache.apply_stock_financial_delta(
            conn,
            stock_value_delta=-_del_stock_value,
            stock_qty_delta=-_del_stock_qty,
            payable_delta=-_del_payable,
            receivable_delta=0,
        )

        conn.commit()


        # 4. Recompute reports and dashboard caches
        try:
            import core.reports_cache as reports_cache

            reports_cache.recompute_all(conn)
            dashboard_cache.recompute_global_snapshot(conn)
            dashboard_cache.refresh_financial_totals(conn)   # full reconcile after delete
            for p in ("today", "week", "month", "lastmonth", "alltime"):
                dashboard_cache.recompute_period(conn, p)
            conn.commit()
        except Exception as e:
            print("Cache recompute error after purchase delete:", e)


@purchases_bp.route("/api/purchase_bill/<int:purchase_id>", methods=["DELETE"])
@purchases_bp.route("/api/purchases/<int:purchase_id>", methods=["DELETE"])
def api_delete_purchase_bill(purchase_id):
    try:
        delete_purchase_bill(purchase_id)
        return jsonify({"status": "ok", "message": "Purchase bill deleted successfully"})
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500




@purchases_bp.route("/api/purchase_returns", methods=["GET"])
def get_purchase_returns():
    """Return list of saved purchase return lines (from purchase_return_items)."""
    date_from = request.args.get("from") or request.args.get("date_from")
    date_to = request.args.get("to") or request.args.get("date_to")
    try:
        page = max(int(request.args.get("page") or 1), 1)
    except (TypeError, ValueError):
        page = 1
    try:
        limit = max(int(request.args.get("limit") or 100), 1)
    except (TypeError, ValueError):
        limit = 100
    offset = (page - 1) * limit

    with get_conn() as conn:
        where_sql = "WHERE 1=1"
        params = []
        if date_from:
            where_sql += " AND pri.date >= ?"
            params.append(date_from)
        if date_to:
            where_sql += " AND pri.date <= ?"
            params.append(date_to)

        total = conn.execute(
            f"SELECT COUNT(*) c FROM purchase_return_items pri {where_sql}", params
        ).fetchone()["c"]

        rows = conn.execute(f"""
            SELECT pri.return_bill_no, pri.party, pri.item_name AS item, pri.size, pri.qty,
                   pri.buy_total, pri.reason, pri.date, pri.invoice_no, pri.invoice_date,
                   pi.barcode_no
            FROM purchase_return_items pri
            LEFT JOIN purchase_item pi ON pi.id = pri.purchase_item_id
            {where_sql}
            ORDER BY pri.id DESC
            LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()
    entries = [
        {
            "returnBillNo": r["return_bill_no"],
            "party": r["party"],
            "item": r["item"],
            "size": r["size"],
            "qty": float(r["qty"] or 0),
            "buyTotal": float(r["buy_total"] or 0),
            "reason": r["reason"],
            "date": r["date"],
            "invoiceNo": r["invoice_no"],
            "invoiceDate": r["invoice_date"],
            "barcode": r["barcode_no"],
        }
        for r in rows
    ]
    return jsonify({"entries": entries, "total": total, "page": page, "limit": limit})


@purchases_bp.route("/api/purchase_invoices/search", methods=["GET"])
def api_purchase_invoices_search():
    q = (request.args.get("q") or "").strip()
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT ph.id, ph.invoice_no, ph.date, ph.status,
                   pt.party_name AS party, pp.total_with_gst
            FROM purchases_header ph
            LEFT JOIN parties pt ON pt.party_id = ph.party_id
            LEFT JOIN purchase_payments pp ON pp.purchase_id = ph.id
            WHERE ph.invoice_no ILIKE ? OR pt.party_name ILIKE ?
            ORDER BY ph.date DESC LIMIT 50
        """, (f"%{q}%", f"%{q}%")).fetchall()
    return jsonify([
        {
            "sourceTable": "purchases_header",
            "purchase_id": r["id"],
            "invoiceNo": r["invoice_no"],
            "date": r["date"],
            "status": r["status"],
            "party": r["party"],
            "total_with_gst": r["total_with_gst"],
        }
        for r in rows
    ])


@purchases_bp.route("/api/purchase_invoices/<table>/<int:purchase_id>", methods=["GET"])
def api_purchase_invoice_items(table, purchase_id):
    with get_conn() as conn:
        items = conn.execute("""
            SELECT product_id AS id, item_name AS item, size, qty, sold, remaining,
                   unit_price AS buy, margin, total_buy_price AS buyTotal, department
            FROM products WHERE purchase_id = ?
        """, (purchase_id,)).fetchall()
    return jsonify([dict(r) for r in items])


@purchases_bp.route("/api/purchase_return_bill", methods=["POST"])
def api_purchase_return_bill():
    """Return by product line or barcode — marks purchase_item.is_returned, adjusts products."""
    from core.accounting import VoucherEngine
    data = request.json or {}
    items = data.get("items") or []
    reason = data.get("reason") or ""
    if not items:
        return jsonify({"status": "error", "message": "No items"}), 400

    with get_conn() as conn:
        today = datetime.now().strftime("%Y%m%d")
        prefix = f"PR{today}-"
        # Simple sequential return number without a dedicated returns table
        max_r = conn.execute(
            "SELECT COUNT(DISTINCT return_bill_no) c FROM purchase_return_items"
        ).fetchone()["c"]
        return_bill_no = f"{prefix}{str(max_r + 1).zfill(4)}"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total_return_value = 0.0
        total_return_gst = 0.0
        party_name = ""
        last_prod = None
        party_debits = {}
        try:
            for it in items:
                qty = float(it.get("qty") or it.get("return_qty") or 1)
                product_id = it.get("id") or it.get("product_id") or it.get("originalId")
                barcode = it.get("barcode") or it.get("barcode_no") or it.get("code")
                # Reset per line so each purchase_return_items row records only
                # this line's own party/value, not a stale value from a
                # previous line in the same request.
                party_name = ""
                line_return_value = 0.0
                last_pi_id = None

                if barcode:
                    try:
                        code_int = int(str(barcode).strip())
                    except ValueError:
                        raise ValueError(f"Invalid barcode {barcode}")
                    pi_rows = conn.execute("""
                        SELECT * FROM purchase_item
                        WHERE barcode_no = ? AND product_id IS NOT NULL
                          AND COALESCE(is_returned,0)=0 AND is_available='available'
                    """, (code_int,)).fetchall()
                    if not pi_rows:
                        raise ValueError(f"Barcode {barcode} not available for return")
                    for pi in pi_rows[:int(qty)]:
                        conn.execute("""
                            UPDATE purchase_item SET is_returned=1, is_available='returned', sold_at=?
                            WHERE barcode_no=?
                        """, (now, pi["barcode_no"]))
                        conn.execute("""
                            UPDATE products SET
                                qty = GREATEST(qty - 1, 0),
                                remaining = GREATEST(remaining - 1, 0),
                                total_buy_price = GREATEST(total_buy_price - ?, 0),
                                projected_margin = unit_price * (margin/100.0) * GREATEST(remaining - 1, 0)
                            WHERE product_id = ?
                        """, (float(pi["buy_price"] or 0), pi["product_id"]))
                        total_return_value += float(pi["buy_price"] or 0)
                        line_return_value += float(pi["buy_price"] or 0)
                        product_id = pi["product_id"]
                        last_pi_id = pi["id"]
                elif product_id:
                    avail = conn.execute("""
                        SELECT id, barcode_no, buy_price, product_id FROM purchase_item
                        WHERE product_id = ? AND COALESCE(is_returned,0)=0 AND is_available='available'
                        ORDER BY id LIMIT ?
                    """, (product_id, int(qty))).fetchall()
                    if len(avail) < int(qty):
                        raise ValueError(f"Only {len(avail)} units available to return")
                    for pi in avail:
                        conn.execute("""
                            UPDATE purchase_item SET is_returned=1, is_available='sold', sold_at=?
                            WHERE barcode_no=?
                        """, (now, pi["barcode_no"]))
                        total_return_value += float(pi["buy_price"] or 0)
                        line_return_value += float(pi["buy_price"] or 0)
                        last_pi_id = pi["id"]
                    conn.execute("""
                        UPDATE products SET
                            qty = GREATEST(qty - ?, 0),
                            remaining = GREATEST(remaining - ?, 0),
                            total_buy_price = GREATEST(total_buy_price - ?, 0),
                            projected_margin = unit_price * (margin/100.0) * GREATEST(remaining - ?, 0)
                        WHERE product_id = ?
                    """, (qty, qty, line_return_value, qty, product_id))
                else:
                    raise ValueError("Each return item needs product id or barcode")

                # Adjust purchase_payments for the bill
                if product_id:
                    prod = conn.execute("""
                        SELECT p.purchase_id, p.party_id, p.item_name, p.size,
                               ph.invoice_no, ph.date AS invoice_date, ph.status AS invoice_status
                        FROM products p
                        LEFT JOIN purchases_header ph ON ph.id = p.purchase_id
                        WHERE p.product_id=?
                    """, (product_id,)).fetchone()
                    if prod and prod["purchase_id"]:
                        last_prod = prod
                        pp = conn.execute(
                            "SELECT * FROM purchase_payments WHERE purchase_id=?",
                            (prod["purchase_id"],)
                        ).fetchone()
                        if pp:
                            gst_rate = float(pp["cgst"] or 0) + float(pp["sgst"] or 0) + float(pp["igst"] or 0)
                            line_gst = round2(line_return_value * (gst_rate / 100.0))
                            total_return_gst += line_gst
                            line_with_gst = line_return_value + line_gst

                            new_total = max(0.0, float(pp["total_buy_amount"] or 0) - line_return_value)
                            new_with_gst = max(0.0, float(pp["total_with_gst"] or 0) - line_with_gst)
                            paid = float(pp["paid_amount"] or 0)
                            new_remaining = max(0.0, new_with_gst - paid)
                            conn.execute("""
                                UPDATE purchase_payments SET
                                    total_buy_amount=?, total_with_gst=?,
                                    remaining_amount=?
                                WHERE purchase_id=?
                            """, (new_total, new_with_gst, new_remaining, prod["purchase_id"]))
                        else:
                            line_with_gst = line_return_value

                        pt = conn.execute(
                            "SELECT party_name FROM parties WHERE party_id=?",
                            (prod["party_id"],)
                        ).fetchone() if prod.get("party_id") else None
                        if pt:
                            party_name = pt["party_name"]

                        is_credit_purchase = prod["invoice_status"] in ("Credit", "Partial", "Overdue")
                        if is_credit_purchase and prod["purchase_id"]:
                            hdr_row = conn.execute("SELECT due_date FROM purchases_header WHERE id=?", (prod["purchase_id"],)).fetchone()
                            due_date = hdr_row["due_date"] if hdr_row else None
                            new_bill_status = resolve_credit_bill_status(new_remaining, paid, due_date)
                            conn.execute(
                                "UPDATE purchases_header SET status = ? WHERE id = ?",
                                (new_bill_status, prod["purchase_id"])
                            )
                            if new_bill_status == 'Paid' and prod.get("party_id"):
                                open_bills = conn.execute("""
                                    SELECT COUNT(*) c FROM purchases_header
                                    WHERE party_id = ? AND status IN ('Credit','Partial','Overdue') AND id != ?
                                """, (prod["party_id"], prod["purchase_id"])).fetchone()["c"]
                                if open_bills == 0:
                                    conn.execute(
                                        "UPDATE parties SET status = 'Cash' WHERE party_id = ?",
                                        (prod["party_id"],)
                                    )

                        # Track party debits for reversing voucher
                        party_key = (party_name or "Unknown", is_credit_purchase)
                        party_debits[party_key] = party_debits.get(party_key, 0.0) + line_with_gst

                        dashboard_cache.apply_transaction_delta(
                            conn, prod["invoice_date"] or now,
                            purchases_delta=-line_return_value,
                            credit_purchases_delta=-line_return_value if is_credit_purchase else 0,
                        )
                        dashboard_cache.adjust_recent_purchase_amount(
                            conn, prod["invoice_date"] or now,
                            prod["invoice_no"], -line_return_value
                        )
                        # O(1) stock/payable delta: returning items reduces both
                        # our stock and (for credit purchases) the outstanding payable.
                        if pp:
                            old_remaining = float(pp["remaining_amount"] or 0)
                            new_remaining = max(0.0, new_with_gst - paid)
                            payable_reduction = max(0.0, old_remaining - new_remaining) if is_credit_purchase else 0.0
                        else:
                            payable_reduction = 0.0
                        dashboard_cache.apply_stock_financial_delta(
                            conn,
                            stock_value_delta=-line_return_value,
                            stock_qty_delta=-qty,
                            payable_delta=-payable_reduction,
                            receivable_delta=0,
                        )

                    # Persist this return line so it can actually be listed
                    # later (previously nothing about the return -- bill no,
                    # reason, qty, value -- was ever saved anywhere).
                    conn.execute("""
                        INSERT INTO purchase_return_items
                            (return_bill_no, purchase_item_id, product_id, party,
                             item_name, size, qty, buy_price, buy_total, reason, date,
                             invoice_no, invoice_date)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        return_bill_no, last_pi_id, product_id, party_name,
                        prod["item_name"] if prod else None,
                        prod["size"] if prod else None,
                        qty,
                        (line_return_value / qty) if qty else 0,
                        line_return_value,
                        reason,
                        datetime.now().strftime("%Y-%m-%d"),
                        prod["invoice_no"] if prod else None,
                        prod["invoice_date"] if prod else None,
                    ))

            # Reversing voucher
            try:
                purchase_ledger = conn.execute("SELECT id FROM ledgers WHERE name='Purchase'").fetchone()
                gst_input_ledger = conn.execute("SELECT id FROM ledgers WHERE name='GST Input'").fetchone()
                cash_ledger = conn.execute("SELECT id FROM ledgers WHERE name='Cash'").fetchone()

                entries = []
                for (p_name, is_credit), p_total_with_gst in party_debits.items():
                    if p_total_with_gst <= 0.001:
                        continue
                    if is_credit and p_name and p_name != "Unknown":
                        p_lid = get_or_create_ledger(p_name, "Sundry Creditors", "Credit", conn)
                        entries.append({"ledger_id": p_lid, "debit": p_total_with_gst, "credit": 0})
                    else:
                        if cash_ledger:
                            entries.append({"ledger_id": cash_ledger["id"], "debit": p_total_with_gst, "credit": 0})

                if purchase_ledger and total_return_value > 0:
                    entries.append({"ledger_id": purchase_ledger["id"], "debit": 0, "credit": total_return_value})
                if gst_input_ledger and total_return_gst > 0.001:
                    entries.append({"ledger_id": gst_input_ledger["id"], "debit": 0, "credit": total_return_gst})

                if len(entries) > 1:
                    VoucherEngine.create_voucher({
                        "voucher_type": "PURCHASERET",
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "reference": return_bill_no,
                        "narration": f"Purchase return {reason}".strip(),
                        "created_by": "admin",
                        "entries": entries
                    }, conn=conn)
            except Exception as e:
                print(f"Purchase return voucher warning: {e}")

        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400
        dashboard_cache.refresh_financial_totals(conn)
        conn.commit()
    _trigger_async_cache_recompute()
    return jsonify({"status": "ok", "returnBillNo": return_bill_no})


@purchases_bp.route("/api/generate_bill_no", methods=["GET"])
def generate_bill_no():
    with get_conn() as conn:
        result = conn.execute("""
            SELECT MAX(CAST(NULLIF(regexp_replace(bill_no, '[^0-9]', '', 'g'), '') AS BIGINT)) as max_num
            FROM sales WHERE bill_no IS NOT NULL
        """).fetchone()
        next_num = (result["max_num"] or 0) + 1
        bill_no = str(next_num).zfill(4)
    return jsonify({"billNo": bill_no})


@purchases_bp.route("/api/purchase_parties", methods=["GET"])
def get_purchase_parties():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT party_name AS party FROM parties WHERE party_name IS NOT NULL AND party_name != '' ORDER BY party_name"
        ).fetchall()
    return jsonify([r["party"] for r in rows])
