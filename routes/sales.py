from datetime import datetime

from flask import Blueprint, request, jsonify

from core.db import get_conn
from core.accounting import VoucherEngine
from core.shared_helpers import get_or_create_ledger

sales_bp = Blueprint("sales", __name__)

def update_sale_bill(sale_id, header_data, items):
    """
    Update an existing sale bill.
    - header_data: dict with customer_name, customer_no, bill_no, date, payment_mode, discount
    - items: list of dict, each with 'id' (sale_items.id) and updated fields:
        item, size, qty, buy_price, margin, sell_price, discount
    - Returns updated sale_id on success.
    - Adjusts inventory (purchase_items.sold and barcode status) based on qty changes.
    - New items require a 'code' (barcode) to sell.
    - Updates sales_borrow if credit mode.
    """
    with get_conn() as conn:
        cur_header = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
        if not cur_header:
            raise ValueError(f"Sale {sale_id} not found")

        # Fetch existing sale_items with their purchase_item_id and barcode_code
        old_items = conn.execute("""
            SELECT id, qty, purchase_item_id, barcode_code
            FROM sale_items
            WHERE sale_id = ?
        """, (sale_id,)).fetchall()
        old_items_map = {row['id']: dict(row) for row in old_items}

        # Update header
        conn.execute("""
            UPDATE sales SET
                bill_no = ?,
                customer_name = ?,
                customer_no = ?,
                date = ?,
                payment_mode = ?,
                discount = ?
            WHERE id = ?
        """, (
            header_data.get('bill_no', ''),
            header_data.get('customer_name', ''),
            header_data.get('customer_no', ''),
            header_data.get('date', datetime.now().strftime("%Y-%m-%d %H:%M")),
            header_data.get('payment_mode', 'Cash'),
            float(header_data.get('discount', 0)),
            sale_id
        ))

        existing_item_ids = set()
        total_sell = 0
        total_buy = 0
        total_profit = 0

        for item_data in items:
            item_id = item_data.get('id')
            if item_id:
                existing_item_ids.add(item_id)
                old = old_items_map.get(item_id)
                if not old:
                    raise ValueError(f"Item {item_id} not found in this sale")
                old_qty = float(old['qty'])
                new_qty = float(item_data.get('qty', old_qty))
                buy_price = float(item_data.get('buy_price', 0))
                margin = float(item_data.get('margin', 0))
                sell_price = float(item_data.get('sell_price', 0))
                discount = float(item_data.get('discount', 0))

                # Recompute totals
                if sell_price > 0:
                    sell_unit = sell_price
                else:
                    sell_unit = buy_price * (1 + margin / 100) * (1 - discount / 100)
                buy_total = new_qty * buy_price
                sell_total = new_qty * sell_unit
                profit = sell_total - buy_total

                # Adjust inventory based on quantity change
                diff = new_qty - old_qty
                purchase_item_id = old['purchase_item_id']
                if diff > 0:
                    # Need to sell additional units
                    if not purchase_item_id:
                        raise ValueError(f"Cannot increase qty for item '{item_data.get('item', '')}' because no purchase_item_id linked.")
                    # Find available barcodes for this purchase_item
                    barcodes = conn.execute("""
                        SELECT code FROM barcodes
                        WHERE purchase_item_id = ? AND status = 'available'
                        ORDER BY id
                        LIMIT ?
                    """, (purchase_item_id, int(diff))).fetchall()
                    if len(barcodes) < diff:
                        raise ValueError(f"Not enough available stock to increase qty by {diff} for item '{item_data.get('item', '')}'")
                    for bc in barcodes:
                        conn.execute("""
                            UPDATE barcodes
                            SET status = 'sold', sold_at = ?
                            WHERE code = ?
                        """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), bc['code']))
                        conn.execute("""
                            UPDATE purchase_items
                            SET sold = sold + 1
                            WHERE id = ?
                        """, (purchase_item_id,))
                elif diff < 0:
                    # Need to revert units
                    # We have stored barcode_code for this sale_item (old['barcode_code'])
                    # Revert that many barcodes (we only have one per item normally, but handle multiple)
                    revert_count = int(-diff)
                    # Find the barcodes that were sold for this sale_item (we stored one code, but if qty>1 we might have multiple)
                    # Since we store only one code per sale_item, we can only revert that one.
                    # If diff < -1, we need to revert more, but we don't have more codes stored.
                    # We'll disallow decreasing by more than 1 if we only have one code.
                    # For simplicity, we allow revert up to the number of stored codes (which is 1).
                    # If the user wants to decrease by more, they should delete the item and add a new one.
                    if revert_count > 1:
                        raise ValueError("Cannot decrease qty by more than 1 for a single sale item. Please delete and re-add if needed.")
                    if old['barcode_code']:
                        conn.execute("""
                            UPDATE barcodes
                            SET status = 'available', sold_at = NULL
                            WHERE code = ? AND status = 'sold'
                        """, (old['barcode_code'],))
                        conn.execute("""
                            UPDATE purchase_items
                            SET sold = sold - 1
                            WHERE id = ?
                        """, (purchase_item_id,))
                    else:
                        raise ValueError(f"Cannot revert stock for item without barcode_code.")

                # Update sale_item
                conn.execute("""
                    UPDATE sale_items SET
                        item = ?,
                        size = ?,
                        qty = ?,
                        buy_price = ?,
                        margin = ?,
                        sell_price = ?,
                        buy_total = ?,
                        sell_total = ?,
                        profit = ?,
                        discount = ?
                    WHERE id = ?
                """, (
                    item_data.get('item', ''),
                    item_data.get('size', ''),
                    new_qty,
                    buy_price,
                    margin,
                    sell_unit,
                    buy_total,
                    sell_total,
                    profit,
                    discount,
                    item_id
                ))

                total_sell += sell_total
                total_buy += buy_total
                total_profit += profit

            else:
                # New item – require a barcode code to sell
                code = item_data.get('code')
                if not code:
                    raise ValueError("New items require a barcode code.")
                # Look up barcode
                bc = conn.execute("SELECT purchase_item_id, sell_price, buy_price, margin FROM barcodes WHERE code = ? AND status = 'available'", (code,)).fetchone()
                if not bc:
                    raise ValueError(f"Barcode {code} not available or not found.")
                purchase_item_id = bc['purchase_item_id']
                # Use provided buy_price/margin/sell_price or from barcode
                buy_price = float(item_data.get('buy_price', bc['buy_price']))
                margin = float(item_data.get('margin', bc['margin']))
                sell_price = float(item_data.get('sell_price', 0))
                discount = float(item_data.get('discount', 0))
                qty = float(item_data.get('qty', 1))
                if qty <= 0 or buy_price <= 0:
                    continue
                sell_unit = sell_price if sell_price > 0 else buy_price * (1 + margin / 100) * (1 - discount / 100)
                buy_total = qty * buy_price
                sell_total = qty * sell_unit
                profit = sell_total - buy_total

                # Mark barcode sold
                conn.execute("""
                    UPDATE barcodes
                    SET status = 'sold', sold_at = ?
                    WHERE code = ?
                """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), code))
                conn.execute("""
                    UPDATE purchase_items
                    SET sold = sold + 1
                    WHERE id = ?
                """, (purchase_item_id,))

                cur = conn.execute("""
                    INSERT INTO sale_items
                    (sale_id, item, size, qty, buy_price, margin, sell_price,
                     buy_total, sell_total, profit, discount, purchase_item_id, barcode_code)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    sale_id,
                    item_data.get('item', ''),
                    item_data.get('size', ''),
                    qty,
                    buy_price,
                    margin,
                    sell_unit,
                    buy_total,
                    sell_total,
                    profit,
                    discount,
                    purchase_item_id,
                    code
                ))
                new_item_id = cur.lastrowid
                existing_item_ids.add(new_item_id)

                total_sell += sell_total
                total_buy += buy_total
                total_profit += profit

        # Delete items not in update list – revert their inventory
        all_item_ids = set(r['id'] for r in conn.execute("SELECT id FROM sale_items WHERE sale_id = ?", (sale_id,)).fetchall())
        to_delete = all_item_ids - existing_item_ids
        for del_id in to_delete:
            del_item = old_items_map.get(del_id)
            if del_item and del_item['barcode_code']:
                # Revert the barcode
                conn.execute("""
                    UPDATE barcodes
                    SET status = 'available', sold_at = NULL
                    WHERE code = ? AND status = 'sold'
                """, (del_item['barcode_code'],))
                conn.execute("""
                    UPDATE purchase_items
                    SET sold = sold - 1
                    WHERE id = ?
                """, (del_item['purchase_item_id'],))
            # Delete the sale_item
            conn.execute("DELETE FROM sale_items WHERE id = ?", (del_id,))

        # Update sale totals
        conn.execute("""
            UPDATE sales
            SET total_sell = ?, total_buy = ?, total_profit = ?
            WHERE id = ?
        """, (total_sell, total_buy, total_profit, sale_id))

        # If credit mode, update sales_borrow
        mode = cur_header['mode']
        if mode == 'credit':
            borrow = conn.execute("SELECT * FROM sales_borrow WHERE sale_id = ?", (sale_id,)).fetchone()
            if borrow:
                new_balance = total_sell - borrow['received_amount']
                new_status = 'Paid' if new_balance <= 0.01 else ('Partial' if borrow['received_amount'] > 0 else 'Pending')
                conn.execute("""
                    UPDATE sales_borrow
                    SET total_amount = ?, balance_amount = ?, status = ?, updated_at = ?
                    WHERE sale_id = ?
                """, (total_sell, new_balance, new_status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), sale_id))

        conn.commit()
        return sale_id

def get_sale_bill(sale_id):
    """Return header and items for a single sale bill."""
    with get_conn() as conn:
        header = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
        if not header:
            return None
        items = conn.execute("SELECT * FROM sale_items WHERE sale_id = ?", (sale_id,)).fetchall()
        return dict(header), [dict(it) for it in items]

def create_sale_bill(header_data, items, mode):
    """
    Inserts a sale header and items. For credit sales, creates sales_borrow.
    Returns sale ID.
    """
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO sales
            (bill_no, customer_name, customer_no, date, mode, payment_mode, discount)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            header_data.get('bill_no', ''),
            header_data.get('customer_name', ''),
            header_data.get('customer_no', ''),
            header_data.get('date', datetime.now().strftime("%Y-%m-%d %H:%M")),
            mode,
            header_data.get('payment_mode', 'Cash') if mode == 'cash' else 'Credit',
            header_data.get('discount', 0)
        ))
        sale_id = cur.lastrowid

        total_sell = 0
        total_buy = 0
        total_profit = 0

        for item in items:
            qty = float(item.get('qty', 1))
            buy_price = float(item.get('buy_price', 0))
            margin = float(item.get('margin', 0))
            discount = float(header_data.get('discount', 0))
            actual_sell_price = float(item.get('sell_price', 0) or 0)
            if actual_sell_price > 0:
                sell_price = round(actual_sell_price * (1 - discount / 100), 2)
            else:
                sell_price = buy_price * (1 + margin / 100) * (1 - discount / 100)
            buy_total = qty * buy_price
            sell_total = qty * sell_price
            profit = sell_total - buy_total

            # Get code from item first
            code = item.get('code')
            purchase_item_id = None
            barcode_code = None
            if code:
                bc = conn.execute("SELECT purchase_item_id FROM barcodes WHERE code = ?", (code,)).fetchone()
                if bc:
                    purchase_item_id = bc['purchase_item_id']
                    barcode_code = code

            cur_item = conn.execute("""
                INSERT INTO sale_items
                (sale_id, item, size, qty, buy_price, margin, sell_price,
                 buy_total, sell_total, profit, discount, purchase_item_id, barcode_code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sale_id,
                item.get('item', ''),
                item.get('size', ''),
                qty,
                buy_price,
                margin,
                sell_price,
                buy_total,
                sell_total,
                profit,
                discount,
                purchase_item_id,
                barcode_code
            ))

            total_sell += sell_total
            total_buy += buy_total
            total_profit += profit

            # Mark ALL scanned barcodes as sold.
            # scanned_codes holds every barcode scanned for this cart item.
            # Fall back to [code] for single-barcode items or older callers.
            scanned_codes_list = item.get('scanned_codes')
            if scanned_codes_list and len(scanned_codes_list) > 0:
                codes_to_mark = scanned_codes_list
            elif code:
                codes_to_mark = [code]
            else:
                codes_to_mark = []

            for bc_code in codes_to_mark:
                bc_code = str(bc_code).strip()
                if not bc_code:
                    continue
                # Fetch purchase_item_id directly per barcode — avoid stale outer variable
                bc_row = conn.execute(
                    "SELECT purchase_item_id FROM barcodes WHERE code = ? AND status = 'available'",
                    (bc_code,)
                ).fetchone()
                if not bc_row:
                    # Already sold or not found — skip to avoid double-counting
                    continue
                conn.execute("""
                    UPDATE barcodes
                    SET status = 'sold', sold_at = ?
                    WHERE code = ? AND status = 'available'
                """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), bc_code))
                conn.execute("""
                    UPDATE purchase_items
                    SET sold = sold + 1
                    WHERE id = ?
                """, (bc_row['purchase_item_id'],))

        conn.execute("""
            UPDATE sales
            SET total_sell = ?, total_buy = ?, total_profit = ?
            WHERE id = ?
        """, (total_sell, total_buy, total_profit, sale_id))

        if mode == 'credit':
            advance_amount = float(header_data.get('advance_amount', 0) or 0)
            # Clamp so we never store a received amount greater than the bill total
            advance_amount = max(0.0, min(advance_amount, total_sell))
            balance_amount = total_sell - advance_amount
            status = 'Paid' if balance_amount <= 0 else ('Partial' if advance_amount > 0 else 'Pending')

            conn.execute("""
                INSERT INTO sales_borrow
                (sale_id, bill_no, customer_name, customer_phone, total_amount, received_amount, balance_amount, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sale_id,
                header_data.get('bill_no', ''),
                header_data.get('customer_name', ''),
                header_data.get('customer_no', ''),
                total_sell,
                advance_amount,
                balance_amount,
                status
            ))

            # If some amount was already received at the time of sale, record it
            # as a receipt in the ledger (debit Cash, credit Debtor), matching
            # what happens when a payment is collected later via the borrow tab.
            if advance_amount > 0:
                customer_ledger = get_or_create_ledger(header_data.get('customer_name', ''), "Sundry Debtors", "Debit", conn)
                cash_ledger = get_or_create_ledger("Cash", "Cash-in-Hand", "Debit", conn)
                voucher_data = {
                    "voucher_type": "RECEIPT",
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "reference": header_data.get('bill_no', ''),
                    "narration": f"Advance received from {header_data.get('customer_name', '')} at time of sale",
                    "entries": [
                        {"ledger_id": cash_ledger, "debit": advance_amount},
                        {"ledger_id": customer_ledger, "credit": advance_amount}
                    ]
                }
                VoucherEngine.create_voucher(voucher_data, conn=conn)

        conn.commit()
        return sale_id

def get_sale_rows(filters=None, limit=None, offset=None):
    """Returns list of sale items joined with header, matching old row structure.

    `limit`/`offset` are optional and backward compatible: when omitted, behaves
    exactly as before (returns every matching row). Callers that need to avoid
    pulling 1 lakh+ rows into memory/network on every load should pass these.
    """
    with get_conn() as conn:
        query = """
            SELECT
                s.id as sale_id,
                s.bill_no,
                s.customer_name,
                s.customer_no,
                s.date,
                s.mode,
                s.payment_mode,
                s.discount,
                si.id as item_id,
                si.item,
                si.size,
                si.qty,
                si.buy_price as buy,
                si.margin,
                si.sell_price as sellUnit,
                si.buy_total as buyTotal,
                si.sell_total as sellTotal,
                si.profit
            FROM sales s
            JOIN sale_items si ON s.id = si.sale_id
            WHERE 1=1
        """
        params = []
        if filters:
            if 'mode' in filters:
                query += " AND s.mode = ?"
                params.append(filters['mode'])
            if 'date_from' in filters:
                query += " AND s.date >= ?"
                params.append(filters['date_from'])
            if 'date_to' in filters:
                query += " AND s.date <= ?"
                params.append(filters['date_to'] + ' 23:59:59')
            if 'customer' in filters and filters['customer']:
                query += " AND s.customer_name LIKE ?"
                params.append(f"%{filters['customer']}%")
            if 'bill_no' in filters and filters['bill_no']:
                query += " AND s.bill_no LIKE ?"
                params.append(f"%{filters['bill_no']}%")
            if 'item' in filters and filters['item']:
                query += " AND si.item LIKE ?"
                params.append(f"%{filters['item']}%")
            if 'payment_type' in filters and filters['payment_type']:
                query += " AND s.mode = ?"
                params.append(filters['payment_type'])
        sort = filters.get('sort', 'date_desc') if filters else 'date_desc'
        if sort == 'date_asc':
            query += " ORDER BY s.date ASC, s.id ASC"
        else:
            query += " ORDER BY s.date DESC, s.id DESC"

        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params = params + [limit, offset or 0]

        rows = conn.execute(query, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d['id'] = d['item_id']
            result.append(d)
        return result


def get_sale_stats(filters=None):
    """Count + qty/buyTotal/sellTotal/profit sums for the Reports > Analyze
    stat cards, computed with a single SQL aggregate query instead of
    pulling every matching row (potentially 100k+) over the network just to
    add them up in JS. Same filter set as get_sale_rows/_count."""
    with get_conn() as conn:
        query = """
            SELECT
                COUNT(*) as cnt,
                COALESCE(SUM(si.qty), 0) as qty,
                COALESCE(SUM(si.buy_total), 0) as buyTotal,
                COALESCE(SUM(si.sell_total), 0) as sellTotal,
                COALESCE(SUM(si.profit), 0) as profit
            FROM sales s
            JOIN sale_items si ON s.id = si.sale_id
            WHERE 1=1
        """
        params = []
        if filters:
            if 'mode' in filters:
                query += " AND s.mode = ?"
                params.append(filters['mode'])
            if 'date_from' in filters:
                query += " AND s.date >= ?"
                params.append(filters['date_from'])
            if 'date_to' in filters:
                query += " AND s.date <= ?"
                params.append(filters['date_to'] + ' 23:59:59')
        row = conn.execute(query, params).fetchone()
        return {
            'count': row['cnt'],
            'qty': row['qty'],
            'buyTotal': row['buyTotal'],
            'sellTotal': row['sellTotal'],
            'profit': row['profit'],
        }


def get_sale_rows_count(filters=None):
    """Row count for the same filter set as get_sale_rows, for pagination meta."""
    with get_conn() as conn:
        query = """
            SELECT COUNT(*) as cnt
            FROM sales s
            JOIN sale_items si ON s.id = si.sale_id
            WHERE 1=1
        """
        params = []
        if filters:
            if 'mode' in filters:
                query += " AND s.mode = ?"
                params.append(filters['mode'])
            if 'date_from' in filters:
                query += " AND s.date >= ?"
                params.append(filters['date_from'])
            if 'date_to' in filters:
                query += " AND s.date <= ?"
                params.append(filters['date_to'] + ' 23:59:59')
            if 'customer' in filters and filters['customer']:
                query += " AND s.customer_name LIKE ?"
                params.append(f"%{filters['customer']}%")
            if 'bill_no' in filters and filters['bill_no']:
                query += " AND s.bill_no LIKE ?"
                params.append(f"%{filters['bill_no']}%")
            if 'item' in filters and filters['item']:
                query += " AND si.item LIKE ?"
                params.append(f"%{filters['item']}%")
            if 'payment_type' in filters and filters['payment_type']:
                query += " AND s.mode = ?"
                params.append(filters['payment_type'])
        return conn.execute(query, params).fetchone()['cnt']

@sales_bp.route("/api/sale_bill", methods=["POST"])
def api_sale_bill():
    try:
        data = request.json
        header = data.get('header', {})
        items = data.get('items', [])
        mode = data.get('mode', 'cash')
        if not items:
            return jsonify({"status": "error", "msg": "No items"}), 400

        sale_id = create_sale_bill(header, items, mode)
        return jsonify({"status": "ok", "sale_id": sale_id})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "msg": str(e)}), 500

@sales_bp.route("/api/sale_bill/<int:sale_id>", methods=["GET"])
def api_get_sale_bill(sale_id):
    result = get_sale_bill(sale_id)
    if not result:
        return jsonify({"error": "Sale not found"}), 404
    header, items = result
    return jsonify({"header": header, "items": items})

@sales_bp.route("/api/sale_bill/<int:sale_id>", methods=["PUT"])
def api_update_sale_bill(sale_id):
    try:
        data = request.json
        header = data.get('header', {})
        items = data.get('items', [])
        if not items:
            return jsonify({"status": "error", "msg": "No items"}), 400
        updated_id = update_sale_bill(sale_id, header, items)
        return jsonify({"status": "ok", "sale_id": updated_id})
    except ValueError as e:
        return jsonify({"status": "error", "msg": str(e)}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "msg": str(e)}), 500

@sales_bp.route("/api/sales_returns", methods=["GET"])
def get_sales_returns():
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    page = request.args.get('page', type=int)
    limit = request.args.get('limit', type=int)

    conditions = []
    params = []
    if date_from:
        conditions.append("date >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("date <= ?")
        params.append(date_to + ' 23:59:59')
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_conn() as conn:
        if page and limit:
            offset = (page - 1) * limit
            rows = conn.execute(
                f"SELECT * FROM sales_returns{where} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [limit, offset]
            ).fetchall()
            total = conn.execute(f"SELECT COUNT(*) as cnt FROM sales_returns{where}", params).fetchone()['cnt']
            return jsonify({'entries': [dict(r) for r in rows], 'total': total, 'page': page, 'limit': limit})

        rows = conn.execute(f"SELECT * FROM sales_returns{where} ORDER BY id DESC", params).fetchall()
    return jsonify([dict(r) for r in rows])

@sales_bp.route("/api/sale_bills/search", methods=["GET"])
def api_sale_bills_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT si.id, s.bill_no as billNo, s.customer_name as customerName
            FROM sale_items si
            JOIN sales s ON s.id = si.sale_id
            WHERE s.bill_no LIKE ? OR s.customer_name LIKE ?
            ORDER BY s.id DESC
        """, (f"%{q}%", f"%{q}%")).fetchall()
    result = [dict(r) for r in rows]
    for r in result:
        r["sourceTable"] = "sale_items"
    return jsonify(result)

@sales_bp.route("/api/sale_bills/<table>/<bill_no>", methods=["GET"])
def api_sale_bill_items(table, bill_no):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT si.id, si.item, si.size, si.qty, si.sell_price as sellUnit
            FROM sale_items si
            JOIN sales s ON s.id = si.sale_id
            WHERE s.bill_no = ?
        """, (bill_no,)).fetchall()
    return jsonify([dict(r) for r in rows])

@sales_bp.route("/api/sales_return_bill", methods=["POST"])
def api_sales_return_bill():
    data = request.json or {}
    items = data.get("items", [])
    reason = data.get("reason", "")
    if not items:
        return jsonify({"status": "error", "message": "No items selected"}), 400

    with get_conn() as conn:
        today = datetime.now().strftime("%Y%m%d")
        prefix = f"SR{today}-"
        result = conn.execute("""
            SELECT MAX(CAST(SUBSTR(returnBillNo, LENGTH(?) + 1) AS INTEGER)) as max_num
            FROM sales_returns WHERE returnBillNo LIKE ? || '%'
        """, (prefix, prefix)).fetchone()
        next_num = (result["max_num"] if result["max_num"] else 0) + 1
        return_bill_no = f"{prefix}{str(next_num).zfill(4)}"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for it in items:
            # Fetch sale_item with purchase_item_id and barcode_code
            si = conn.execute("""
                SELECT si.item, si.size, si.sell_price, si.purchase_item_id, si.barcode_code,
                       s.customer_name, s.customer_no, s.bill_no
                FROM sale_items si
                JOIN sales s ON s.id = si.sale_id
                WHERE si.id = ?
            """, (it.get("originalId"),)).fetchone()
            if not si:
                continue
            qty = float(it.get("qty", 0))
            sell_unit = si["sell_price"] or 0

            # Adjust inventory: decrement sold on purchase_item and mark barcode as available
            purchase_item_id = si["purchase_item_id"]
            barcode_code = si["barcode_code"]
            if purchase_item_id:
                # Decrement sold by the returned quantity
                conn.execute("""
                    UPDATE purchase_items
                    SET sold = sold - ?
                    WHERE id = ? AND sold >= ?
                """, (qty, purchase_item_id, qty))
                # If barcode code exists, revert its status to 'available'
                if barcode_code:
                    conn.execute("""
                        UPDATE barcodes
                        SET status = 'available', sold_at = NULL
                        WHERE code = ? AND status = 'sold'
                    """, (barcode_code,))

            conn.execute("""
                INSERT INTO sales_returns
                (returnBillNo, date, customerName, customerNo, item, size, qty,
                 sellUnit, sellTotal, originalBillNo, originalTable, originalId, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                return_bill_no, now, si["customer_name"], si["customer_no"],
                si["item"], si["size"], qty, sell_unit, qty * sell_unit,
                si["bill_no"], it.get("originalTable", ""), it.get("originalId"), reason
            ))
        conn.commit()
    return jsonify({"status": "ok", "returnBillNo": return_bill_no})

@sales_bp.route("/api/replace_sale", methods=["POST"])
def api_replace_sale():
    """
    Handles the Sales > Replace/Exchange flow.
    - oldItems: items the customer is returning (barcodes must currently be 'sold').
    - newItems: items being handed over instead (barcodes must currently be 'available').
    Restores stock for old items, deducts stock for new items, and saves a
    Replace Bill with the price difference (positive = customer pays,
    negative = shop refunds the customer).
    """
    data = request.json or {}
    customer_name = data.get("customerName", "").strip()
    customer_no = data.get("customerNo", "").strip()
    note = data.get("note", "").strip()
    old_items = data.get("oldItems", [])
    new_items = data.get("newItems", [])

    if not old_items and not new_items:
        return jsonify({"status": "error", "message": "Add at least one item to replace."}), 400

    with get_conn() as conn:
        # Validate everything first so we never apply a partial change
        old_rows = []
        for itm in old_items:
            scanned_codes = itm.get("scanned_codes") or [str(itm.get("code", "")).strip()]
            for code in scanned_codes:
                code = str(code).strip()
                if not code:
                    continue
                bc = conn.execute("SELECT * FROM barcodes WHERE code=?", (code,)).fetchone()
                if not bc or bc["status"] != "sold":
                    return jsonify({"status": "error", "message": f"Barcode {code} is not a sold item. It cannot be returned."}), 400
                bc = dict(bc)
                si = conn.execute(
                    "SELECT sell_price FROM sale_items WHERE barcode_code=? ORDER BY id DESC LIMIT 1", (code,)
                ).fetchone()
                sell_price = si["sell_price"] if si else (bc["sell_price"] or 0)
                old_rows.append({
                    "item": bc["product_name"], "size": bc["size"], "sell_price": sell_price,
                    "barcode_code": code, "purchase_item_id": bc["purchase_item_id"]
                })

        discount = float(data.get("discount", 0) or 0)
        if discount < 0:
            discount = 0
        if discount > 99.9:
            discount = 99.9

        new_rows = []
        for itm in new_items:
            scanned_codes = itm.get("scanned_codes") or [str(itm.get("code", "")).strip()]
            for code in scanned_codes:
                code = str(code).strip()
                if not code:
                    continue
                bc = conn.execute("SELECT * FROM barcodes WHERE code=?", (code,)).fetchone()
                if not bc or bc["status"] != "available":
                    return jsonify({"status": "error", "message": f"Barcode {code} is not available to give as a replacement."}), 400
                bc = dict(bc)
                raw_sell_price = bc["sell_price"] or 0
                discounted_sell_price = round(raw_sell_price * (1 - discount / 100), 2) if discount > 0 else raw_sell_price
                new_rows.append({
                    "item": bc["product_name"], "size": bc["size"], "sell_price": discounted_sell_price,
                    "barcode_code": code, "purchase_item_id": bc["purchase_item_id"]
                })

        if not old_rows and not new_rows:
            return jsonify({"status": "error", "message": "No valid items to process."}), 400

        # Everything checked out — apply stock changes
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        old_total = 0
        for row in old_rows:
            conn.execute("UPDATE barcodes SET status='available', sold_at=NULL WHERE code=?", (row["barcode_code"],))
            if row["purchase_item_id"]:
                conn.execute("UPDATE purchase_items SET sold = sold - 1 WHERE id=? AND sold >= 1", (row["purchase_item_id"],))
            old_total += row["sell_price"]

        new_total = 0
        for row in new_rows:
            conn.execute("UPDATE barcodes SET status='sold', sold_at=? WHERE code=?", (now, row["barcode_code"]))
            if row["purchase_item_id"]:
                conn.execute("UPDATE purchase_items SET sold = sold + 1 WHERE id=?", (row["purchase_item_id"],))
            new_total += row["sell_price"]

        old_total = round(old_total, 2)
        new_total = round(new_total, 2)
        difference = round(new_total - old_total, 2)

        today = datetime.now().strftime("%Y%m%d")
        prefix = f"RX{today}-"
        result = conn.execute("""
            SELECT MAX(CAST(SUBSTR(replaceBillNo, LENGTH(?) + 1) AS INTEGER)) as max_num
            FROM replace_bills WHERE replaceBillNo LIKE ? || '%'
        """, (prefix, prefix)).fetchone()
        next_num = (result["max_num"] if result["max_num"] else 0) + 1
        replace_bill_no = f"{prefix}{str(next_num).zfill(4)}"

        cur = conn.execute("""
            INSERT INTO replace_bills
            (replaceBillNo, date, customerName, customerNo, oldTotal, newTotal, difference, note, discount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (replace_bill_no, now, customer_name, customer_no, old_total, new_total, difference, note, discount))
        replace_bill_id = cur.lastrowid

        for row in old_rows:
            conn.execute("""
                INSERT INTO replace_bill_items
                (replace_bill_id, side, item, size, qty, sell_price, sell_total, barcode_code, purchase_item_id)
                VALUES (?, 'old', ?, ?, 1, ?, ?, ?, ?)
            """, (replace_bill_id, row["item"], row["size"], row["sell_price"], row["sell_price"],
                  row["barcode_code"], row["purchase_item_id"]))

        for row in new_rows:
            conn.execute("""
                INSERT INTO replace_bill_items
                (replace_bill_id, side, item, size, qty, sell_price, sell_total, barcode_code, purchase_item_id)
                VALUES (?, 'new', ?, ?, 1, ?, ?, ?, ?)
            """, (replace_bill_id, row["item"], row["size"], row["sell_price"], row["sell_price"],
                  row["barcode_code"], row["purchase_item_id"]))

    return jsonify({
        "status": "ok",
        "replaceBillNo": replace_bill_no,
        "oldTotal": old_total,
        "newTotal": new_total,
        "difference": difference,
        "totalReplacePrice": round(old_total + new_total, 2)
    })

@sales_bp.route("/api/replace_bills", methods=["GET"])
def get_replace_bills():
    with get_conn() as conn:
        headers = conn.execute("SELECT * FROM replace_bills ORDER BY id DESC").fetchall()
        result = []
        for h in headers:
            h = dict(h)
            items = conn.execute(
                "SELECT side, item, size, qty, sell_price, sell_total FROM replace_bill_items WHERE replace_bill_id=?",
                (h["id"],)
            ).fetchall()
            h["items"] = [dict(i) for i in items]
            result.append(h)
    return jsonify(result)

@sales_bp.route("/api/replace_bill/<int:replace_bill_id>", methods=["GET"])
def api_get_replace_bill(replace_bill_id):
    with get_conn() as conn:
        header = conn.execute("SELECT * FROM replace_bills WHERE id=?", (replace_bill_id,)).fetchone()
        if not header:
            return jsonify({"error": "Replace bill not found"}), 404
        header = dict(header)
        items = conn.execute(
            "SELECT id, side, item, size, qty, sell_price, sell_total, barcode_code FROM replace_bill_items WHERE replace_bill_id=? ORDER BY id",
            (replace_bill_id,)
        ).fetchall()
        header["items"] = [dict(i) for i in items]
    return jsonify(header)

@sales_bp.route("/api/replace_bill/<int:replace_bill_id>", methods=["PUT"])
def api_update_replace_bill(replace_bill_id):
    """
    Edits a Replace Bill's billing figures only (date, customer, note,
    discount, item rate/qty). Does NOT touch barcode/stock status —
    those were already applied when the replace bill was created.
    """
    data = request.json or {}
    header = data.get("header", {})
    items = data.get("items", [])

    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM replace_bills WHERE id=?", (replace_bill_id,)).fetchone()
        if not existing:
            return jsonify({"status": "error", "message": "Replace bill not found"}), 404

        discount = float(header.get("discount", 0) or 0)
        if discount < 0:
            discount = 0
        if discount > 99.9:
            discount = 99.9

        old_total = 0
        new_total_raw = 0
        for itm in items:
            item_id = itm.get("id")
            if not item_id:
                continue
            qty = float(itm.get("qty", 1) or 1)
            sell_price = float(itm.get("sell_price", 0) or 0)
            side = itm.get("side")
            sell_total = round(qty * sell_price, 2)
            conn.execute("""
                UPDATE replace_bill_items SET qty=?, sell_price=?, sell_total=?
                WHERE id=? AND replace_bill_id=?
            """, (qty, sell_price, sell_total, item_id, replace_bill_id))
            if side == 'old':
                old_total += sell_total
            elif side == 'new':
                new_total_raw += sell_total

        old_total = round(old_total, 2)
        new_total = round(new_total_raw * (1 - discount / 100), 2) if discount > 0 else round(new_total_raw, 2)
        difference = round(new_total - old_total, 2)

        conn.execute("""
            UPDATE replace_bills
            SET date=?, customerName=?, customerNo=?, note=?, discount=?, oldTotal=?, newTotal=?, difference=?
            WHERE id=?
        """, (
            header.get("date", ""), header.get("customerName", "").strip(), header.get("customerNo", "").strip(),
            header.get("note", "").strip(), discount, old_total, new_total, difference, replace_bill_id
        ))

    return jsonify({"status": "ok", "oldTotal": old_total, "newTotal": new_total, "difference": difference})

@sales_bp.route("/api/generate_invoice_no", methods=["GET"])
def generate_invoice_no():
    with get_conn() as conn:
        today = datetime.now().strftime("%Y%m%d")
        prefix = f"P{today}-"
        result = conn.execute("""
            SELECT MAX(CAST(SUBSTR(invoice_no, LENGTH(?) + 1) AS INTEGER)) as max_num
            FROM purchases WHERE invoice_no LIKE ? || '%'
        """, (prefix, prefix)).fetchone()
        next_num = (result["max_num"] if result["max_num"] else 0) + 1
        invoice_no = f"{prefix}{str(next_num).zfill(4)}"
    return jsonify({"invoiceNo": invoice_no})
