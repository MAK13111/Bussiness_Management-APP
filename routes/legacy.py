from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify

from core.db import get_conn
from core.accounting import VoucherEngine
from core.shared_helpers import get_or_create_ledger
from routes.purchases import (
    create_purchase_bill, get_purchase_rows, get_purchase_rows_count, get_purchase_stats,
    resolve_credit_bill_status, sync_overdue_purchase_statuses,
)
from routes.sales import create_sale_bill, get_sale_rows, get_sale_rows_count, get_sale_stats

legacy_bp = Blueprint("legacy", __name__)


@legacy_bp.route("/api/entries/stats", methods=["GET"])
def get_entries_stats():
    typ = request.args.get("type") or "purchase"
    filters = {}
    if request.args.get("from"):
        filters["date_from"] = request.args.get("from")
    if request.args.get("to"):
        filters["date_to"] = request.args.get("to")
    if request.args.get("mode"):
        filters["mode"] = request.args.get("mode")
    if typ in ("sale", "sell", "sales"):
        s = get_sale_stats(filters)
        return jsonify({
            "count": s.get("total_sells", 0),
            "qty": s.get("total_qty", 0),
            "buyTotal": s.get("total_cost", 0),
            "sellTotal": s.get("total_sell_amt", 0),
            "profit": s.get("total_profit", 0),
        })
    s = get_purchase_stats(filters)
    return jsonify({
        "count": s.get("total_entries", 0),
        "qty": s.get("total_qty", 0),
        "buyTotal": s.get("total_purchase", 0),
        "sellTotal": s.get("total_sell", 0),
        "profit": s.get("total_profit", 0),
    })


@legacy_bp.route("/api/entries", methods=["GET"])
def get_entries():
    """Frontend expects a plain JSON array of entry rows."""
    typ = request.args.get("type") or "purchase"
    filters = {}
    if request.args.get("from"):
        filters["date_from"] = request.args.get("from")
    if request.args.get("to"):
        filters["date_to"] = request.args.get("to")
    if request.args.get("mode"):
        filters["mode"] = request.args.get("mode")
    if request.args.get("party"):
        filters["party"] = request.args.get("party")
    if request.args.get("search"):
        filters["search"] = request.args.get("search")
    if request.args.get("sold_only") in ("1", "true", "True"):
        filters["sold_only"] = True
    limit = request.args.get("limit", type=int)
    page = request.args.get("page", type=int)
    total_param = request.args.get("total", type=int) or request.args.get("known_total", type=int)
    offset = ((page - 1) * limit) if (page and limit) else (request.args.get("offset", type=int) or 0)
    if typ in ("sale", "sell", "sales"):
        rows = get_sale_rows(filters, limit=limit, offset=offset)
        total = total_param if (total_param is not None and total_param > 0) else get_sale_rows_count(filters)
        # camelCase aliases used by older sell stats loops
        for r in rows:
            r["buyTotal"] = r.get("buy_total") or r.get("buyTotal") or 0
            r["sellTotal"] = r.get("sell_total") or r.get("sellTotal") or 0
            # sales/bills.js reads itm.sellUnit for the per-item Rate
            # column -- without this alias it was always undefined,
            # so Rate showed as ₹0.00 even on bills with a real price.
            r["sellUnit"] = r.get("sell_price") or r.get("sellUnit") or 0
            r["profit"] = r.get("profit") or 0
    else:
        rows = get_purchase_rows(filters, limit=limit, offset=offset)
        total = total_param if (total_param is not None and total_param > 0) else get_purchase_rows_count(filters)
        for r in rows:
            # aliases for main.js renderPurchase loops
            r["buyTotal"] = r.get("buyTotal") or r.get("buy_total") or 0
            r["sellTotal"] = r.get("sellTotal") or r.get("sell_total") or 0
            r["profit"] = r.get("profit") or 0
            # aliases for ui/drawer.js showPurchaseDetail, which reads
            # e.sellerNo / e.invoiceNo / e.sellerAddress (camelCase), not
            # the snake_case keys get_purchase_rows returns.
            r["sellerNo"] = r.get("seller_no") or ""
            r["sellerAddress"] = r.get("seller_address") or ""
            r["invoiceNo"] = r.get("invoice_no") or ""
            r["sellerGstNo"] = r.get("seller_gst_no") or ""
            
    if page and limit:
        return jsonify({"entries": rows, "total": total, "page": page, "limit": limit})
    return jsonify(rows)


@legacy_bp.route("/api/entries", methods=["POST"])
def add_entry():
    data = request.json or {}
    typ = data.get("type") or "purchase"
    mode = data.get("mode") or "cash"
    if typ == "sale":
        sid = create_sale_bill(data, data.get("items") or [], mode)
        return jsonify({"status": "ok", "id": sid})
    pid = create_purchase_bill(data, data.get("items") or [], mode)
    return jsonify({"status": "ok", "id": pid})


@legacy_bp.route("/api/entries/<int:row_id>", methods=["PUT"])
def update_entry(row_id):
    return jsonify({"status": "ok", "message": "Use /api/purchase_bill or /api/sale_bill PUT"})


@legacy_bp.route("/api/entries/<int:row_id>", methods=["DELETE"])
def delete_entry(row_id):
    return jsonify({"status": "error", "message": "Delete not supported in new schema"}, 400)


def _date_range(preset):
    today = datetime.now().date()
    if preset == "today":
        return str(today), str(today)
    if preset == "yesterday":
        y = today - timedelta(days=1)
        return str(y), str(y)
    if preset == "this_week":
        start = today - timedelta(days=today.weekday())
        return str(start), str(today)
    if preset == "this_month":
        return str(today.replace(day=1)), str(today)
    if preset == "last_month":
        first = today.replace(day=1)
        last_month_end = first - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        return str(last_month_start), str(last_month_end)
    return None, None


@legacy_bp.route("/api/borrow/summary", methods=["GET"])
def api_borrow_summary():
    typ = request.args.get("type") or "purchase"  # purchase | sales
    with get_conn() as conn:
        if typ == "sales":
            row = conn.execute("""
                SELECT
                    COALESCE(SUM(CASE WHEN s.status IN ('Credit','Partial')
                        THEN COALESCE(sp.remaining_amount, COALESCE(sp.total_amount, s.total_sale_price) - COALESCE(sp.cash,0) - COALESCE(sp.online,0))
                        ELSE 0 END), 0) as total_borrow,
                    COUNT(*) FILTER (WHERE s.status IN ('Credit','Partial')) as pending_bills,
                    0 as paid_today,
                    COUNT(*) FILTER (
                        WHERE s.status IN ('Credit','Partial')
                        AND s.due_date IS NOT NULL AND s.due_date < CURRENT_DATE
                    ) as overdue_bills
                FROM sales s
                LEFT JOIN sales_payments sp ON sp.sale_id = s.sale_id
            """).fetchone()
        else:
            # Bring stored purchase statuses in line with due dates before
            # reading anything, so 'Overdue' reflects reality in the DB
            # rather than only being computed for this one response.
            sync_overdue_purchase_statuses(conn)
            row = conn.execute("""
                SELECT
                    COALESCE(SUM(CASE WHEN ph.status IN ('Credit','Partial','Overdue')
                        THEN pp.remaining_amount ELSE 0 END), 0) as total_borrow,
                    COUNT(*) FILTER (WHERE ph.status IN ('Credit','Partial','Overdue')) as pending_bills,
                    COALESCE((
                        SELECT SUM(pp2.paid_amount) FROM purchase_payments pp2
                        JOIN purchases_header ph2 ON ph2.id = pp2.purchase_id
                        WHERE ph2.status = 'Paid' AND ph2.created_at::date = CURRENT_DATE
                    ), 0) as paid_today,
                    COUNT(*) FILTER (WHERE ph.status = 'Overdue') as overdue_bills
                FROM purchases_header ph
                LEFT JOIN purchase_payments pp ON pp.purchase_id = ph.id
            """).fetchone()
    return jsonify({
        "total_borrow": float(row["total_borrow"] or 0),
        "pending_bills": int(row["pending_bills"] or 0),
        "paid_today": float(row["paid_today"] or 0),
        "overdue_bills": int(row["overdue_bills"] or 0),
        # camelCase aliases
        "totalBorrow": float(row["total_borrow"] or 0),
        "pendingBills": int(row["pending_bills"] or 0),
        "paidToday": float(row["paid_today"] or 0),
        "overdueBills": int(row["overdue_bills"] or 0),
    })


@legacy_bp.route("/api/borrow/list", methods=["GET"])
def api_borrow_list():
    typ = request.args.get("type") or "purchase"
    status = request.args.get("status") or "all"
    sort = request.args.get("sort") or "latest"
    search = (request.args.get("search") or request.args.get("party") or "").strip()
    date_from = request.args.get("date_from") or request.args.get("from")
    date_to = request.args.get("date_to") or request.args.get("to")
    preset = request.args.get("preset")
    if preset:
        date_from, date_to = _date_range(preset)

    with get_conn() as conn:
        if typ == "sales":
            query = """
                SELECT s.sale_id AS id, s.date, s.bill_no AS bill_no,
                       c.customer_name AS party, c.customer_no AS phone,
                       s.total_sale_price AS total,
                       COALESCE(sp.paid_amount, COALESCE(sp.cash,0)+COALESCE(sp.online,0)) AS paid,
                       COALESCE(sp.remaining_amount, s.total_sale_price - COALESCE(sp.cash,0)-COALESCE(sp.online,0)) AS balance,
                       s.due_date AS due_date, s.status
                FROM sales s
                LEFT JOIN customers c ON c.customer_id = s.customers_id
                LEFT JOIN sales_payments sp ON sp.sale_id = s.sale_id
                WHERE s.status IN ('Credit','Partial','Paid')
            """
            params = []
            if status and status != "all":
                query += " AND LOWER(s.status) = LOWER(?)"
                params.append(status)
            if date_from:
                query += " AND s.date >= ?"
                params.append(date_from)
            if date_to:
                query += " AND s.date <= ?"
                params.append(date_to)
            if search:
                query += " AND (c.customer_name ILIKE ? OR s.bill_no ILIKE ?)"
                params.extend([f"%{search}%", f"%{search}%"])
            bid = request.args.get("id")
            if bid:
                query += " AND s.sale_id = ?"
                params.append(bid)
            if sort == "oldest":
                query += " ORDER BY s.date ASC, s.sale_id ASC"
            elif sort == "highest":
                query += " ORDER BY s.total_sale_price DESC"
            elif sort == "lowest":
                query += " ORDER BY s.total_sale_price ASC"
            else:
                query += " ORDER BY s.date DESC, s.sale_id DESC"
        else:
            # Sync stored status against due dates first so display_status
            # (which is just ph.status) reflects Overdue correctly.
            sync_overdue_purchase_statuses(conn)
            query = """
                SELECT ph.id, ph.date, ph.invoice_no AS bill_no,
                       pt.party_name AS party, pt.contact_no AS phone,
                       pp.total_with_gst AS total, pp.paid_amount AS paid,
                       pp.remaining_amount AS balance,
                       ph.due_date AS due_date, ph.status
                FROM purchases_header ph
                LEFT JOIN parties pt ON pt.party_id = ph.party_id
                LEFT JOIN purchase_payments pp ON pp.purchase_id = ph.id
                WHERE ph.status IN ('Credit','Partial','Paid','Overdue')
            """
            params = []
            if status and status != "all":
                query += " AND LOWER(ph.status) = LOWER(?)"
                params.append(status)
            if date_from:
                query += " AND ph.date >= ?"
                params.append(date_from)
            if date_to:
                query += " AND ph.date <= ?"
                params.append(date_to)
            if search:
                query += " AND (pt.party_name ILIKE ? OR ph.invoice_no ILIKE ?)"
                params.extend([f"%{search}%", f"%{search}%"])
            bid = request.args.get("id")
            if bid:
                query += " AND ph.id = ?"
                params.append(bid)
            if sort == "oldest":
                query += " ORDER BY ph.date ASC, ph.id ASC"
            elif sort == "highest":
                query += " ORDER BY pp.total_with_gst DESC"
            elif sort == "lowest":
                query += " ORDER BY pp.total_with_gst ASC"
            else:
                query += " ORDER BY ph.date DESC, ph.id DESC"
        page = request.args.get("page", type=int) or 1
        limit = request.args.get("limit", type=int) or 100
        offset = (page - 1) * limit

        total = conn.execute("SELECT COUNT(*) c " + query[query.index("FROM"):query.index("ORDER BY")], params).fetchone()["c"]
        query += " LIMIT ? OFFSET ?"
        rows = conn.execute(query, params + [limit, offset]).fetchall()
    # Shape expected by payment.js renderBorrowTable
    out = []
    for r in rows:
        d = dict(r)
        d["party_name"] = d.get("party") or d.get("party_name") or ""
        d["display_status"] = d.get("status") or "Pending"
        d["created_at"] = str(d.get("date") or "")
        d["bill_no"] = d.get("bill_no") or ""
        d["phone"] = d.get("phone") or ""
        d["total"] = float(d.get("total") or 0)
        d["paid"] = float(d.get("paid") or 0)
        d["balance"] = float(d.get("balance") or 0)
        out.append(d)
    return jsonify({"rows": out, "total": total, "page": page, "limit": limit})



@legacy_bp.route("/api/borrow/payment", methods=["POST"])
def api_borrow_payment():
    """Record payment against a credit purchase or sale bill — updates in-place payment row."""
    data = request.json or {}
    typ = data.get("type") or data.get("borrow_type") or "purchase"
    bill_id = data.get("id") or data.get("borrow_id") or data.get("purchase_id") or data.get("sale_id")
    amount = float(data.get("amount") or 0)
    mode = data.get("payment_mode") or data.get("mode") or "Cash"
    pay_date = data.get("payment_date") or datetime.now().strftime("%Y-%m-%d")
    if not bill_id or amount <= 0:
        return jsonify({"error": "id and amount required"}), 400

    with get_conn() as conn:
        if typ in ("sales", "sale"):
            sale = conn.execute("SELECT * FROM sales WHERE sale_id=?", (bill_id,)).fetchone()
            if not sale:
                return jsonify({"error": "Sale not found"}), 404
            sp = conn.execute("SELECT * FROM sales_payments WHERE sale_id=?", (bill_id,)).fetchone()
            if not sp:
                return jsonify({"error": "Payment row missing"}), 404
            paid_so_far = float(sp["paid_amount"] or 0)
            total = float(sp["total_amount"] or sale["total_sale_price"] or 0)
            amount = min(amount, max(0.0, total - paid_so_far))
            if amount <= 0:
                return jsonify({"error": "Bill already fully paid"}), 400
            new_paid = paid_so_far + amount
            new_remaining = max(0.0, total - new_paid)
            if mode.lower() in ("upi", "bank", "online", "card"):
                conn.execute(
                    """UPDATE sales_payments
                       SET online = COALESCE(online,0) + ?, paid_amount = ?, remaining_amount = ?
                       WHERE sale_id=?""",
                    (amount, new_paid, new_remaining, bill_id)
                )
            else:
                conn.execute(
                    """UPDATE sales_payments
                       SET cash = COALESCE(cash,0) + ?, paid_amount = ?, remaining_amount = ?
                       WHERE sale_id=?""",
                    (amount, new_paid, new_remaining, bill_id)
                )
            if new_paid >= total - 0.01:
                new_status = "Paid"
            elif new_paid > 0:
                new_status = "Partial"
            else:
                new_status = "Credit"
            conn.execute("UPDATE sales SET status=? WHERE sale_id=?", (new_status, bill_id))
            try:
                cash_l = get_or_create_ledger("Cash", "Cash-in-Hand", "Debit", conn)
                cust = conn.execute(
                    "SELECT customer_name FROM customers WHERE customer_id=?",
                    (sale["customers_id"],)
                ).fetchone()
                cname = cust["customer_name"] if cust else "Customer"
                party_l = get_or_create_ledger(cname, "Sundry Debtors", "Debit", conn)
                VoucherEngine.create_voucher({
                    "voucher_type": "RECEIPT",
                    "date": pay_date,
                    "reference": sale["bill_no"] or str(bill_id),
                    "narration": f"Payment received from {cname}",
                    "entries": [
                        {"ledger_id": cash_l, "debit": amount},
                        {"ledger_id": party_l, "credit": amount},
                    ]
                }, conn=conn)
            except Exception as e:
                print(f"Receipt voucher warning: {e}")
        else:
            ph = conn.execute("SELECT * FROM purchases_header WHERE id=?", (bill_id,)).fetchone()
            if not ph:
                return jsonify({"error": "Purchase not found"}), 404
            pp = conn.execute("SELECT * FROM purchase_payments WHERE purchase_id=?", (bill_id,)).fetchone()
            if not pp:
                return jsonify({"error": "Payment row missing"}), 404
            total = float(pp["total_with_gst"] or 0)
            already = float(pp["paid_amount"] or 0)
            amount = min(amount, max(0.0, total - already))
            if amount <= 0:
                return jsonify({"error": "Bill already fully paid"}), 400
            paid = already + amount
            remaining = max(0.0, total - paid)
            new_status = resolve_credit_bill_status(remaining, paid, ph.get("due_date"))
            conn.execute("""
                UPDATE purchase_payments SET
                    paid_amount=?, remaining_amount=?, mode_of_payment=?
                WHERE purchase_id=?
            """, (paid, remaining, mode, bill_id))
            conn.execute("UPDATE purchases_header SET status=? WHERE id=?", (new_status, bill_id))
            prod_status = "Paid" if new_status == "Paid" else "Credit"
            conn.execute(
                "UPDATE products SET status=? WHERE purchase_id=?",
                (prod_status, bill_id)
            )
            if new_status == "Paid" and ph["party_id"]:
                open_bills = conn.execute("""
                    SELECT COUNT(*) c FROM purchases_header
                    WHERE party_id=? AND status IN ('Credit','Partial','Overdue') AND id!=?
                """, (ph["party_id"], bill_id)).fetchone()["c"]
                if open_bills == 0:
                    conn.execute(
                        "UPDATE parties SET status='Cash' WHERE party_id=?",
                        (ph["party_id"],)
                    )
            try:
                cash_l = get_or_create_ledger("Cash", "Cash-in-Hand", "Debit", conn)
                pt = conn.execute(
                    "SELECT party_name FROM parties WHERE party_id=?", (ph["party_id"],)
                ).fetchone()
                pname = pt["party_name"] if pt else "Supplier"
                party_l = get_or_create_ledger(pname, "Sundry Creditors", "Credit", conn)
                VoucherEngine.create_voucher({
                    "voucher_type": "PAYMENT",
                    "date": pay_date,
                    "reference": ph["invoice_no"] or str(bill_id),
                    "narration": f"Payment to {pname}",
                    "entries": [
                        {"ledger_id": party_l, "debit": amount},
                        {"ledger_id": cash_l, "credit": amount},
                    ]
                }, conn=conn)
            except Exception as e:
                print(f"Payment voucher warning: {e}")

        import core.dashboard_cache as dashboard_cache
        dashboard_cache.refresh_financial_totals(conn)

        conn.commit()
    return jsonify({"status": "ok"})


@legacy_bp.route("/api/borrow/history", methods=["GET"])
def api_borrow_history():
    """No separate payment history table — return current payment row snapshot."""
    typ = request.args.get("type") or "purchase"
    bill_id = request.args.get("id") or request.args.get("borrow_id")
    if not bill_id:
        return jsonify([])
    with get_conn() as conn:
        if typ in ("sales", "sale"):
            row = conn.execute("""
                SELECT sp.*, s.bill_no, s.date
                FROM sales_payments sp
                JOIN sales s ON s.sale_id = sp.sale_id
                WHERE sp.sale_id = ?
            """, (bill_id,)).fetchone()
        else:
            row = conn.execute("""
                SELECT pp.*, ph.invoice_no, ph.date
                FROM purchase_payments pp
                JOIN purchases_header ph ON ph.id = pp.purchase_id
                WHERE pp.purchase_id = ?
            """, (bill_id,)).fetchone()
    if not row:
        return jsonify([])
    d = dict(row)
    return jsonify([{
        "amount": d.get("paid_amount") or (float(d.get("cash") or 0) + float(d.get("online") or 0)),
        "payment_mode": d.get("mode_of_payment"),
        "date": d.get("date"),
        "notes": "Cumulative payment record (updated in place)"
    }])
