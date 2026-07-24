from datetime import datetime

from flask import Blueprint, request, jsonify

from core.db import get_conn
from routes.purchases import create_purchase_bill, get_purchase_rows, get_purchase_rows_count, get_purchase_stats
from routes.sales import create_sale_bill, get_sale_rows, get_sale_rows_count, get_sale_stats

legacy_bp = Blueprint("legacy", __name__)

@legacy_bp.route("/api/entries/stats", methods=["GET"])
def get_entries_stats():
    """Lightweight version of /api/entries: returns only the aggregate
    numbers the Reports > Analyze stat cards need (count/qty/totals),
    computed in SQL, instead of every matching row. Used in place of
    /api/entries wherever a caller only needs the stat cards, since on a
    shop with 100k+ bills the full row fetch was the main reason the
    Reports tab felt slow to open."""
    entry_type = request.args.get("type", "purchase")
    mode = request.args.get("mode", "cash")
    filters = {'mode': mode}
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    if date_from:
        filters['date_from'] = date_from
    if date_to:
        filters['date_to'] = date_to
    if entry_type == "purchase":
        return jsonify(get_purchase_stats(filters))
    else:
        return jsonify(get_sale_stats(filters))

@legacy_bp.route("/api/entries", methods=["GET"])
def get_entries():
    entry_type = request.args.get("type", "purchase")
    mode = request.args.get("mode", "cash")
    filters = {'mode': mode}
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    if date_from:
        filters['date_from'] = date_from
    if date_to:
        filters['date_to'] = date_to
    # Used by the Reports > Analyze > Sold Items view to fetch only rows
    # that have actually been sold, instead of the entire purchase_items
    # table (see loadSoldEntries() in static/Scripts/main.js).
    if request.args.get('sold_only') == '1':
        filters['sold_gt_zero'] = True

    # Pagination is opt-in: pass ?page=&limit= to avoid pulling every matching
    # row over the network (same convention as /api/reports/purchases and
    # /api/reports/sales). Without those params the response is unchanged
    # (plain list) for existing callers like loadEntries()/loadSellEntries().
    page = request.args.get('page', type=int)
    limit = request.args.get('limit', type=int)

    if entry_type == "purchase":
        if page and limit:
            offset = (page - 1) * limit
            rows = get_purchase_rows(filters, limit=limit, offset=offset)
            total = get_purchase_rows_count(filters)
            return jsonify({'entries': rows, 'total': total, 'page': page, 'limit': limit})
        rows = get_purchase_rows(filters)
        return jsonify(rows)
    else:
        if page and limit:
            offset = (page - 1) * limit
            rows = get_sale_rows(filters, limit=limit, offset=offset)
            total = get_sale_rows_count(filters)
            return jsonify({'entries': rows, 'total': total, 'page': page, 'limit': limit})
        rows = get_sale_rows(filters)
        return jsonify(rows)

@legacy_bp.route("/api/entries", methods=["POST"])
def add_entry():
    data = request.json
    entry_type = request.args.get("type", "purchase")
    mode = request.args.get("mode", "cash")
    if entry_type == "purchase":
        header = {
            'party': data.get('party', ''),
            'seller_no': data.get('sellerNo', ''),
            'seller_address': data.get('sellerAddress', ''),
            'invoice_no': data.get('invoiceNo', ''),
            'date': data.get('date', datetime.now().strftime("%Y-%m-%d %H:%M")),
            'department': data.get('department', ''),
            'cgst': data.get('cgst', 0),
            'sgst': data.get('sgst', 0),
            'igst': data.get('igst', 0)
        }
        items = [{
            'item': data.get('item', ''),
            'size': data.get('size', ''),
            'qty': data.get('qty', 0),
            'buy': data.get('buy', 0),
            'margin': data.get('margin', 0),
            'cgst': data.get('cgst', 0),
            'sgst': data.get('sgst', 0),
            'igst': data.get('igst', 0),
            'department': data.get('department', '')
        }]
        try:
            create_purchase_bill(header, items, mode)
            return jsonify({"status": "ok"})
        except Exception as e:
            return jsonify({"status": "error", "msg": str(e)}), 500
    else:
        header = {
            'customer_name': data.get('customerName', ''),
            'customer_no': data.get('customerNo', ''),
            'bill_no': data.get('billNo', ''),
            'date': data.get('date', datetime.now().strftime("%Y-%m-%d %H:%M")),
            'payment_mode': data.get('paymentMode', 'Cash'),
            'discount': data.get('discount', 0)
        }
        items = [{
            'item': data.get('item', ''),
            'size': data.get('size', ''),
            'qty': data.get('qty', 1),
            'buy_price': data.get('buy', 0),
            'margin': data.get('margin', 0),
            'code': data.get('baseCode', None)
        }]
        try:
            create_sale_bill(header, items, mode)
            return jsonify({"status": "ok"})
        except Exception as e:
            return jsonify({"status": "error", "msg": str(e)}), 500

@legacy_bp.route("/api/entries/<int:row_id>", methods=["PUT"])
def update_entry(row_id):
    """Update a single purchase_item or sale_item row (legacy flat-entry edit)."""
    data = request.json or {}
    entry_type = request.args.get("type", "purchase")

    if entry_type == "purchase":
        qty = float(data.get("qty", 1) or 1)
        buy = float(data.get("buy", 0) or 0)
        margin = float(data.get("margin", 0) or 0)
        sell_price = round(buy * (1 + margin / 100), 4)
        buy_total = round(qty * buy, 4)
        sell_total = round(qty * sell_price, 4)
        profit = round(sell_total - buy_total, 4)
        cgst = float(data.get("cgst", 0) or 0)
        sgst = float(data.get("sgst", 0) or 0)
        igst = float(data.get("igst", 0) or 0)
        total_with_gst = round(buy_total * (1 + (cgst + sgst + igst) / 100), 4)

        with get_conn() as conn:
            row = conn.execute("SELECT id FROM purchase_items WHERE id = ?", (row_id,)).fetchone()
            if not row:
                return jsonify({"error": "Entry not found"}), 404
            conn.execute("""
                UPDATE purchase_items
                SET item = ?, size = ?, qty = ?, buy_price = ?, margin = ?,
                    sell_price = ?, buy_total = ?, sell_total = ?, profit = ?,
                    cgst = ?, sgst = ?, igst = ?, total_with_gst = ?, department = ?
                WHERE id = ?
            """, (
                (data.get("item") or "").strip(),
                (data.get("size") or "").strip(),
                qty, buy, margin, sell_price, buy_total, sell_total, profit,
                cgst, sgst, igst, total_with_gst,
                (data.get("department") or "").strip(),
                row_id
            ))
            # Also update purchase header fields if present
            purchase_row = conn.execute(
                "SELECT purchase_id FROM purchase_items WHERE id = ?", (row_id,)
            ).fetchone()
            if purchase_row:
                pid = purchase_row["purchase_id"]
                conn.execute("""
                    UPDATE purchases
                    SET party = ?, date = ?, invoice_no = ?, seller_no = ?,
                        seller_address = ?, cgst_rate = ?, sgst_rate = ?, igst_rate = ?,
                        department = ?
                    WHERE id = ?
                """, (
                    (data.get("party") or "").strip(),
                    data.get("date", ""),
                    (data.get("invoiceNo") or "").strip(),
                    (data.get("sellerNo") or "").strip(),
                    (data.get("sellerAddress") or "").strip(),
                    cgst, sgst, igst,
                    (data.get("department") or "").strip(),
                    pid
                ))
            conn.commit()
        return jsonify({"status": "ok"})

    else:  # sell
        qty = float(data.get("qty", 1) or 1)
        buy = float(data.get("buy", 0) or 0)
        margin = float(data.get("margin", 0) or 0)
        discount = float(data.get("discount", 0) or 0)
        sell_price = round(buy * (1 + margin / 100) * (1 - discount / 100), 4)
        buy_total = round(qty * buy, 4)
        sell_total = round(qty * sell_price, 4)
        profit = round(sell_total - buy_total, 4)

        with get_conn() as conn:
            row = conn.execute("SELECT id FROM sale_items WHERE id = ?", (row_id,)).fetchone()
            if not row:
                return jsonify({"error": "Entry not found"}), 404
            conn.execute("""
                UPDATE sale_items
                SET item = ?, size = ?, qty = ?, buy_price = ?, margin = ?,
                    sell_price = ?, buy_total = ?, sell_total = ?, profit = ?,
                    discount = ?
                WHERE id = ?
            """, (
                (data.get("item") or "").strip(),
                (data.get("size") or "").strip(),
                qty, buy, margin, sell_price, buy_total, sell_total, profit,
                discount, row_id
            ))
            # Also update sale header fields if present
            sale_row = conn.execute(
                "SELECT sale_id FROM sale_items WHERE id = ?", (row_id,)
            ).fetchone()
            if sale_row:
                sid = sale_row["sale_id"]
                conn.execute("""
                    UPDATE sales
                    SET customer_name = ?, customer_no = ?, bill_no = ?,
                        date = ?, payment_mode = ?, discount = ?
                    WHERE id = ?
                """, (
                    (data.get("customerName") or "").strip(),
                    (data.get("customerNo") or "").strip(),
                    (data.get("billNo") or "").strip(),
                    data.get("date", ""),
                    (data.get("paymentMode") or "Cash").strip(),
                    discount,
                    sid
                ))
            conn.commit()
        return jsonify({"status": "ok"})


@legacy_bp.route("/api/entries/<int:row_id>", methods=["DELETE"])
def delete_entry(row_id):
    entry_type = request.args.get("type", "purchase")
    if entry_type == "purchase":
        with get_conn() as conn:
            conn.execute("DELETE FROM barcodes WHERE purchase_item_id = ?", (row_id,))
            conn.execute("DELETE FROM purchase_items WHERE id = ?", (row_id,))
            conn.commit()
        return jsonify({"status": "deleted"})
    else:
        with get_conn() as conn:
            conn.execute("DELETE FROM sale_items WHERE id = ?", (row_id,))
            conn.commit()
        return jsonify({"status": "deleted"})

@legacy_bp.route("/api/borrow/summary", methods=["GET"])
def api_borrow_summary():
    borrow_type = request.args.get('type', 'purchase')
    if borrow_type == 'purchase':
        table = 'purchase_borrow'
        amount_col = 'total_amount'
        paid_col = 'paid_amount'
        balance_col = 'balance_amount'
    else:
        table = 'sales_borrow'
        amount_col = 'total_amount'
        paid_col = 'received_amount'
        balance_col = 'balance_amount'

    with get_conn() as conn:
        total_outstanding = conn.execute(f"""
            SELECT COALESCE(SUM({balance_col}), 0) as total
            FROM {table}
        """).fetchone()['total']

        pending_count = conn.execute(f"""
            SELECT COUNT(*) as count
            FROM {table}
            WHERE status != 'Paid'
        """).fetchone()['count']

        today = datetime.now().strftime("%Y-%m-%d")
        paid_today = conn.execute("""
            SELECT COALESCE(SUM(amount), 0) as total
            FROM payments
            WHERE borrow_type = ? AND date(payment_date) = ?
        """, (borrow_type, today)).fetchone()['total']

        overdue_count = conn.execute(f"""
            SELECT COUNT(*) as count
            FROM {table}
            WHERE due_date IS NOT NULL AND due_date < date('now') AND status != 'Paid'
        """).fetchone()['count']

    return jsonify({
        "total_borrow": total_outstanding,
        "pending_bills": pending_count,
        "paid_today": paid_today,
        "overdue_bills": overdue_count
    })

@legacy_bp.route("/api/borrow/list", methods=["GET"])
def api_borrow_list():
    borrow_type = request.args.get('type', 'purchase')
    record_id = request.args.get('id', type=int)
    search = request.args.get('search', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    status_filter = request.args.get('status', '')  # comma-separated
    sort = request.args.get('sort', 'date_desc')
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    offset = (page - 1) * limit

    if borrow_type == 'purchase':
        table = 'purchase_borrow'
        id_col = 'purchase_id'
        name_col = 'party_name'
        phone_col = 'party_phone'
        bill_col = 'invoice_no'
        amount_col = 'total_amount'
        paid_col = 'paid_amount'
        balance_col = 'balance_amount'
        status_col = 'status'
        date_col = 'created_at'
    else:
        table = 'sales_borrow'
        id_col = 'sale_id'
        name_col = 'customer_name'
        phone_col = 'customer_phone'
        bill_col = 'bill_no'
        amount_col = 'total_amount'
        paid_col = 'received_amount'
        balance_col = 'balance_amount'
        status_col = 'status'
        date_col = 'created_at'

    with get_conn() as conn:
        # Build the main query
        query = f"""
            SELECT
                pb.id,
                pb.{id_col} as ref_id,
                pb.{bill_col} as bill_no,
                pb.{name_col} as party_name,
                pb.{phone_col} as phone,
                pb.{amount_col} as total,
                pb.{paid_col} as paid,
                pb.{balance_col} as balance,
                pb.due_date,
                pb.{status_col} as status,
                pb.{date_col} as created_at,
                pb.updated_at
            FROM {table} pb
            WHERE 1=1
        """
        params = []

        # WHERE conditions
        where_clauses = []
        if record_id is not None:
            where_clauses.append("pb.id = ?")
            params.append(record_id)
        if search:
            where_clauses.append(f"(pb.{name_col} LIKE ? OR pb.{bill_col} LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])
        if date_from:
            where_clauses.append(f"date(pb.{date_col}) >= ?")
            params.append(date_from)
        if date_to:
            where_clauses.append(f"date(pb.{date_col}) <= ?")
            params.append(date_to)
        if status_filter and status_filter != 'All' and status_filter != 'Overdue':
            statuses = status_filter.split(',')
            placeholders = ','.join(['?' for _ in statuses])
            where_clauses.append(f"pb.{status_col} IN ({placeholders})")
            params.extend(statuses)
        if status_filter == 'Overdue':
            where_clauses.append(f"pb.due_date IS NOT NULL AND pb.due_date < date('now') AND pb.{status_col} != 'Paid'")

        if where_clauses:
            query += " AND " + " AND ".join(where_clauses)

        # Sorting
        if sort == 'date_asc':
            query += f" ORDER BY pb.{date_col} ASC"
        elif sort == 'amount_desc':
            query += f" ORDER BY pb.{amount_col} DESC"
        elif sort == 'amount_asc':
            query += f" ORDER BY pb.{amount_col} ASC"
        else:  # date_desc default
            query += f" ORDER BY pb.{date_col} DESC"

        # --- Count total records (separate query) ---
        count_query = f"SELECT COUNT(*) as total FROM {table} pb WHERE 1=1"
        if where_clauses:
            count_query += " AND " + " AND ".join(where_clauses)
        # Use the same params (without the sort and limit)
        total_count_row = conn.execute(count_query, params).fetchone()
        total_count = total_count_row['total'] if total_count_row else 0

        # Apply pagination
        query += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        result = [dict(r) for r in rows]

        # Compute display_status
        today = datetime.now().strftime("%Y-%m-%d")
        for row in result:
            if row['due_date'] and row['due_date'] < today and row['status'] != 'Paid':
                row['display_status'] = 'Overdue'
            else:
                row['display_status'] = row['status']

        # Replace None with '-'
        for row in result:
            for k, v in row.items():
                if v is None:
                    row[k] = '-'

        return jsonify({
            "rows": result,
            "total": total_count,
            "page": page,
            "limit": limit,
            "pages": (total_count + limit - 1) // limit
        })

@legacy_bp.route("/api/borrow/payment", methods=["POST"])
def api_borrow_payment():
    data = request.json
    borrow_type = data.get('borrow_type')  # 'purchase' or 'sales'
    borrow_id = data.get('borrow_id')
    amount = float(data.get('amount', 0))
    payment_date = data.get('payment_date', datetime.now().strftime("%Y-%m-%d"))
    payment_mode = data.get('payment_mode', 'Cash')
    reference_no = data.get('reference_no', '')
    notes = data.get('notes', '')

    if amount <= 0:
        return jsonify({"error": "Amount must be positive"}), 400

    with get_conn() as conn:
        # Fetch current borrow record
        if borrow_type == 'purchase':
            table = 'purchase_borrow'
            amount_col = 'total_amount'
            paid_col = 'paid_amount'
            balance_col = 'balance_amount'
        else:
            table = 'sales_borrow'
            amount_col = 'total_amount'
            paid_col = 'received_amount'
            balance_col = 'balance_amount'

        borrow = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (borrow_id,)).fetchone()
        if not borrow:
            return jsonify({"error": "Borrow record not found"}), 404

        current_paid = borrow[paid_col]
        current_balance = borrow[balance_col]

        if round(amount, 2) > round(current_balance, 2):
            return jsonify({"error": f"Amount exceeds remaining balance ({round(current_balance, 2)})"}), 400
        amount = round(amount, 2)

        new_paid = round(current_paid + amount, 2)
        new_balance = round(current_balance - amount, 2)
        status = 'Paid' if new_balance <= 0.01 else 'Partial'

        # Insert payment record
        conn.execute("""
            INSERT INTO payments
            (borrow_type, borrow_id, amount, payment_date, payment_mode, reference_no, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (borrow_type, borrow_id, amount, payment_date, payment_mode, reference_no, notes))

        # Update borrow record
        conn.execute(f"""
            UPDATE {table}
            SET {paid_col} = ?, {balance_col} = ?, status = ?, updated_at = ?
            WHERE id = ?
        """, (new_paid, new_balance, status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), borrow_id))

        conn.commit()
        return jsonify({
            "status": "ok",           # frontend checks this key — must be "ok"
            "payment_status": status, # "Paid" or "Partial" — renamed to avoid overwriting "ok"
            "new_paid": new_paid,
            "new_balance": new_balance
        })

@legacy_bp.route("/api/borrow/history", methods=["GET"])
def api_borrow_history():
    borrow_type = request.args.get('borrow_type')
    borrow_id = request.args.get('borrow_id', type=int)
    if not borrow_type or not borrow_id:
        return jsonify({"error": "borrow_type and borrow_id required"}), 400

    with get_conn() as conn:
        rows = conn.execute("""
            SELECT id, amount, payment_date, payment_mode, reference_no, notes, created_at
            FROM payments
            WHERE borrow_type = ? AND borrow_id = ?
            ORDER BY payment_date DESC, created_at DESC
        """, (borrow_type, borrow_id)).fetchall()
    return jsonify([dict(r) for r in rows])
