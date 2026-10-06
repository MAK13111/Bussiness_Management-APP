import time
from flask import Blueprint, request, jsonify

from core.db import get_conn
from core.shared_helpers import to_camel_row

reports_bp = Blueprint("reports", __name__)


_monthly_cache = {}
_MONTHLY_CACHE_TTL = 30


def _filters_from_args():
    filters = {}
    if request.args.get("from") or request.args.get("date_from"):
        filters["date_from"] = (request.args.get("from") or request.args.get("date_from")).strip()
    if request.args.get("to") or request.args.get("date_to"):
        filters["date_to"] = (request.args.get("to") or request.args.get("date_to")).strip()
    if request.args.get("mode") or request.args.get("payment_type"):
        filters["mode"] = (request.args.get("mode") or request.args.get("payment_type")).strip().lower()
    if request.args.get("party") or request.args.get("customer"):
        filters["party"] = (request.args.get("party") or request.args.get("customer")).strip()
    if request.args.get("item") or request.args.get("product"):
        filters["item"] = (request.args.get("item") or request.args.get("product")).strip()
    if request.args.get("department"):
        filters["department"] = request.args.get("department").strip()
    if request.args.get("search"):
        filters["search"] = request.args.get("search").strip()
    if request.args.get("invoice_no") or request.args.get("bill_no") or request.args.get("bill"):
        filters["invoice_no"] = (request.args.get("invoice_no") or request.args.get("bill_no") or request.args.get("bill")).strip()
    if request.args.get("sort"):
        filters["sort"] = request.args.get("sort").strip()
    return filters


def _purchase_query_parts(filters):
    where = "WHERE ph.status != 'deleted'"
    params = []
    if filters:
        if 'mode' in filters and filters['mode']:
            m = filters['mode'].lower()
            if m == 'cash':
                where += " AND LOWER(ph.status) = 'cash'"
            elif m == 'credit':
                where += " AND LOWER(ph.status) IN ('credit','partial','paid','overdue')"
        if 'date_from' in filters and filters['date_from']:
            where += " AND ph.date >= ?"
            params.append(filters['date_from'])
        if 'date_to' in filters and filters['date_to']:
            where += " AND ph.date <= ?"
            params.append(filters['date_to'])
        if 'party' in filters and filters['party']:
            where += " AND (pt.party_name ILIKE ? OR CAST(ph.party_id AS TEXT) ILIKE ?)"
            p_val = f"%{filters['party']}%"
            params.extend([p_val, p_val])
        if 'invoice_no' in filters and filters['invoice_no']:
            where += " AND (ph.invoice_no ILIKE ? OR CAST(ph.id AS TEXT) ILIKE ?)"
            i_val = f"%{filters['invoice_no']}%"
            params.extend([i_val, i_val])
        if 'item' in filters and filters['item']:
            where += " AND pr.item_name ILIKE ?"
            params.append(f"%{filters['item']}%")
        if 'department' in filters and filters['department']:
            where += " AND pr.department ILIKE ?"
            params.append(f"%{filters['department']}%")
        if filters.get('sold_only'):
            where += " AND pr.sold > 0"
        if filters.get('search'):
            where += " AND (pr.item_name ILIKE ? OR pr.size ILIKE ? OR pt.party_name ILIKE ? OR ph.invoice_no ILIKE ?)"
            like = f"%{filters['search']}%"
            params.extend([like, like, like, like])
    return where, params


def _sale_query_parts(filters):
    where = "WHERE COALESCE(si.is_return, 0) = 0"
    params = []
    if filters:
        if 'mode' in filters and filters['mode']:
            m = filters['mode'].lower()
            if m == 'cash':
                where += " AND (LOWER(s.status) = 'cash' OR LOWER(COALESCE(sp.mode_of_payment, s.status)) = 'cash')"
            elif m == 'credit':
                where += " AND (LOWER(s.status) IN ('credit','partial','paid') OR LOWER(COALESCE(sp.mode_of_payment, s.status)) IN ('credit','partial'))"
        if 'date_from' in filters and filters['date_from']:
            where += " AND s.date >= ?"
            params.append(filters['date_from'])
        if 'date_to' in filters and filters['date_to']:
            where += " AND s.date <= ?"
            params.append(filters['date_to'])
        if 'party' in filters and filters['party']:
            where += " AND (c.customer_name ILIKE ? OR CAST(s.customers_id AS TEXT) ILIKE ?)"
            c_val = f"%{filters['party']}%"
            params.extend([c_val, c_val])
        if 'invoice_no' in filters and filters['invoice_no']:
            where += " AND (s.bill_no ILIKE ? OR CAST(s.sale_id AS TEXT) ILIKE ?)"
            b_val = f"%{filters['invoice_no']}%"
            params.extend([b_val, b_val])
        if 'item' in filters and filters['item']:
            where += " AND si.item_name ILIKE ?"
            params.append(f"%{filters['item']}%")
    return where, params


@reports_bp.route("/api/reports/analyze-initial", methods=["GET"])
def api_reports_analyze_initial():
    mode = request.args.get("mode") or ""
    page = request.args.get("page", type=int) or 1
    limit = request.args.get("limit", type=int) or 100
    offset = (page - 1) * limit
    cache_mode = mode if mode in ("cash", "credit") else "all"

    pur_where = "WHERE ph.status != 'deleted'"
    pur_params = []
    if mode == 'cash':
        pur_where += " AND ph.status = 'Cash'"
    elif mode == 'credit':
        pur_where += " AND ph.status IN ('Credit','Partial','Paid','Overdue')"


    with get_conn() as conn:
        import core.reports_cache as reports_cache
        stats = reports_cache.get_stats(conn, cache_mode)

        bills_rows = conn.execute(f"""
            SELECT
                ph.id as purchase_id, ph.invoice_no, pt.party_name as party,
                pt.contact_no as seller_no, pt.address as seller_address,
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
                COALESCE(pp.total_with_gst, pr.total_buy_price) as "totalWithGST",
                pr.department as item_dept, ph.status
            FROM purchases_header ph
            JOIN products pr ON pr.purchase_id = ph.id
            LEFT JOIN parties pt ON pt.party_id = ph.party_id
            LEFT JOIN purchase_payments pp ON pp.purchase_id = ph.id
            {pur_where}
            ORDER BY ph.date DESC, ph.id DESC, pr.product_id
            LIMIT ? OFFSET ?
        """, pur_params + [int(limit), int(offset)]).fetchall()

    return jsonify({
        "purchaseStats": {
            "count": int(stats["purchase_count"] or 0),
            "qty": float(stats["purchase_qty"] or 0),
            "buyTotal": float(stats["purchase_buy_total"] or 0),
            "sellTotal": float(stats["purchase_sell_total"] or 0),
            "profit": float(stats["purchase_profit"] or 0),
        },
        "sellStats": {
            "count": int(stats["sale_count"] or 0),
            "qty": float(stats["sale_qty"] or 0),
            "buyTotal": float(stats["sale_cost_total"] or 0),
            "sellTotal": float(stats["sale_sell_total"] or 0),
            "profit": float(stats["sale_profit"] or 0),
        },
        "purchaseBills": {
            "entries": [dict(r) for r in bills_rows],
            "total": int(stats["purchase_count"] or 0),
            "page": page,
            "limit": limit,
        },
    })


@reports_bp.route("/api/reports/purchases", methods=["GET"])
def api_reports_purchases():
    filters = _filters_from_args()
    limit = request.args.get("limit", type=int) or 50
    page = request.args.get("page", type=int) or 1
    offset = ((page - 1) * limit) if (page and limit) else (request.args.get("offset", type=int) or 0)
    where, params = _purchase_query_parts(filters)

    sort_val = (filters.get("sort") or request.args.get("sort") or "date_desc").lower()
    sort_dir = "ASC" if sort_val == "date_asc" else "DESC"
    order_by = f"ORDER BY ph.date {sort_dir}, ph.id {sort_dir}, pr.product_id"

    with get_conn() as conn:
        if not filters:
            import core.reports_cache as reports_cache
            stats = reports_cache.get_stats(conn, "all")
            total = int(stats["purchase_count"] or 0)
        else:
            count_row = conn.execute(f"""
                SELECT COUNT(*) AS cnt
                FROM purchases_header ph
                JOIN products pr ON pr.purchase_id = ph.id
                LEFT JOIN parties pt ON pt.party_id = ph.party_id
                {where}
            """, params).fetchone()
            total = int(count_row["cnt"] or 0) if count_row else 0

        rows = conn.execute(f"""
            SELECT
                ph.id as purchase_id, ph.invoice_no, pt.party_name as party,
                pt.contact_no as seller_no, pt.address as seller_address,
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
                COALESCE(pp.total_with_gst, pr.total_buy_price) as "totalWithGST",
                pr.department as item_dept, ph.status
            FROM purchases_header ph
            JOIN products pr ON pr.purchase_id = ph.id
            LEFT JOIN parties pt ON pt.party_id = ph.party_id
            LEFT JOIN purchase_payments pp ON pp.purchase_id = ph.id
            {where}
            {order_by}
            LIMIT ? OFFSET ?
        """, params + [int(limit), int(offset)]).fetchall()

    return jsonify({"entries": [dict(r) for r in rows], "total": total, "page": page, "limit": limit})


@reports_bp.route("/api/reports/sales", methods=["GET"])
def api_reports_sales():
    filters = _filters_from_args()
    limit = request.args.get("limit", type=int) or 50
    page = request.args.get("page", type=int) or 1
    offset = ((page - 1) * limit) if (page and limit) else (request.args.get("offset", type=int) or 0)
    where, params = _sale_query_parts(filters)

    sort_val = (filters.get("sort") or request.args.get("sort") or "date_desc").lower()
    sort_dir = "ASC" if sort_val == "date_asc" else "DESC"
    order_by = f"ORDER BY s.date {sort_dir}, s.sale_id {sort_dir}, si.sold_item_id"

    with get_conn() as conn:
        if not filters:
            import core.reports_cache as reports_cache
            stats = reports_cache.get_stats(conn, "all")
            total = stats["sale_count"]
        else:
            count_query = f"""
                SELECT COUNT(*)
                FROM sales s
                JOIN sold_items si ON si.sale_id = s.sale_id
                LEFT JOIN customers c ON c.customer_id = s.customers_id
                LEFT JOIN sales_payments sp ON sp.sale_id = s.sale_id
                {where}
            """
            res = conn.execute(count_query, params).fetchone()
            total = list(res.values())[0] if res else 0

        rows = conn.execute(f"""
            SELECT
                s.sale_id, s.bill_no, c.customer_name, c.customer_no,
                s.date, CASE WHEN s.status = 'Cash' THEN 'cash' ELSE 'credit' END AS mode,
                s.status, COALESCE(sp.mode_of_payment, s.status) AS payment_mode,
                si.sold_item_id AS item_id, si.item_name AS item, si.size,
                si.quantity AS qty, si.unit_buy_price AS buy_price, si.margin,
                si.unit_sale_price AS sell_price, si.unit_sale_price AS "sellUnit",
                si.total_buy_price AS buy_total, si.total_buy_price AS "buyTotal",
                si.total_sale_price AS sell_total, si.total_sale_price AS "sellTotal",
                (si.total_sale_price - si.total_buy_price) AS profit, s.discount,
                s.gross_before_discount AS "subTotal"
            FROM sales s
            JOIN sold_items si ON si.sale_id = s.sale_id
            LEFT JOIN customers c ON c.customer_id = s.customers_id
            LEFT JOIN sales_payments sp ON sp.sale_id = s.sale_id
            {where}
            {order_by}
            LIMIT ? OFFSET ?
        """, params + [int(limit), int(offset)]).fetchall()

    return jsonify({"entries": [dict(r) for r in rows], "total": total, "page": page, "limit": limit})


@reports_bp.route("/api/reports/replace_bills", methods=["GET"])
def api_reports_replace_bills():
    filters = _filters_from_args()
    date_from = filters.get("date_from")
    date_to = filters.get("date_to")
    party = filters.get("party")
    invoice_no = filters.get("invoice_no")
    sort = filters.get("sort")

    with get_conn() as conn:
        query = "SELECT * FROM replace_bills WHERE 1=1"
        params = []
        if date_from:
            query += " AND date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND date <= ?"
            params.append(date_to)
        if party:
            query += " AND customer_name ILIKE ?"
            params.append(f"%{party}%")
        if invoice_no:
            query += " AND (replace_bill_no ILIKE ? OR CAST(id AS TEXT) ILIKE ?)"
            r_val = f"%{invoice_no}%"
            params.extend([r_val, r_val])

        sort_dir = "ASC" if sort == "date_asc" else "DESC"
        query += f" ORDER BY date {sort_dir}, id {sort_dir}"
        rows = conn.execute(query, params).fetchall()
        bills = [to_camel_row(r) for r in rows]

        bill_ids = [b["id"] for b in bills]
        items_by_bill = {bid: [] for bid in bill_ids}
        if bill_ids:
            placeholders = ",".join("?" for _ in bill_ids)
            item_rows = conn.execute(f"""
                SELECT replace_bill_id, side, item, size, qty, sell_price, sell_total,
                       barcode_code, purchase_item_id
                FROM replace_bill_items
                WHERE replace_bill_id IN ({placeholders})
                ORDER BY id
            """, bill_ids).fetchall()
            for r in item_rows:
                items_by_bill[r["replace_bill_id"]].append(dict(r))

        for b in bills:
            b["items"] = items_by_bill.get(b["id"], [])

    return jsonify(bills)


@reports_bp.route("/api/reports/monthly", methods=["GET"])
def api_reports_monthly():
    year = request.args.get("year", type=int) or __import__("datetime").datetime.now().year
    with get_conn() as conn:
        import core.reports_cache as reports_cache
        data = reports_cache.get_monthly_stats(conn, year)
    return jsonify(data)


@reports_bp.route("/api/reports/profit", methods=["GET"])
def api_reports_profit():
    date_from = request.args.get("from") or request.args.get("date_from")
    date_to = request.args.get("to") or request.args.get("date_to")
    page = request.args.get("page", type=int)
    limit = request.args.get("limit", type=int) or 100
    offset = ((page - 1) * limit) if page else 0

    where = "WHERE COALESCE(si.is_return,0)=0"
    params = []
    if date_from:
        where += " AND s.date >= ?"
        params.append(date_from)
    if date_to:
        where += " AND s.date <= ?"
        params.append(date_to)

    with get_conn() as conn:
        import core.reports_cache as reports_cache
        totals = reports_cache.get_profit_report_totals(conn, date_from, date_to)

        rows = conn.execute(f"""
            SELECT s.date, c.customer_name AS party,
                   si.item_name AS item, si.quantity AS qty,
                   si.total_buy_price AS buy_total, si.total_sale_price AS sell_total,
                   (si.total_sale_price - si.total_buy_price) AS profit
            FROM sales s
            JOIN sold_items si ON si.sale_id = s.sale_id
            LEFT JOIN customers c ON c.customer_id = s.customers_id
            {where}
            ORDER BY s.date DESC, s.sale_id DESC, si.sold_item_id
            LIMIT ? OFFSET ?
        """, params + [int(limit), int(offset)]).fetchall()

    entries = [
        {
            "date": r["date"],
            "party": r["party"],
            "item": r["item"],
            "qty": r["qty"],
            "buyTotal": float(r["buy_total"] or 0),
            "sellTotal": float(r["sell_total"] or 0),
            "profit": float(r["profit"] or 0),
        }
        for r in rows
    ]

    return jsonify({
        "entries": entries,
        "totals": {
            "purchases": totals["purchases"],
            "sales": totals["sales"],
            "profit": totals["profit"],
            "marginPct": totals["marginPct"],
        },
        "total": totals["total_rows"],
        "page": page,
        "limit": limit,
    })


@reports_bp.route("/api/reports/deleted_purchases", methods=["GET"])
def api_reports_deleted_purchases():
    filters = _filters_from_args()
    limit = request.args.get("limit", type=int) or 100
    page = request.args.get("page", type=int) or 1
    offset = (page - 1) * limit

    with get_conn() as conn:
        count_row = conn.execute("""
            SELECT COUNT(*) AS cnt
            FROM purchases_header ph
            JOIN products pr ON pr.purchase_id = ph.id
            WHERE ph.status = 'deleted'
        """).fetchone()
        total = int(count_row["cnt"] or 0) if count_row else 0

        rows = conn.execute("""
            SELECT
                ph.id as purchase_id, ph.invoice_no, pt.party_name as party,
                pt.contact_no as seller_no, pt.address as seller_address,
                ph.date, pr.department,
                'deleted' as mode,
                pr.product_id as id, pr.product_id as item_id,
                pr.item_name as item, pr.size, pr.qty, pr.sold, pr.remaining,
                pr.unit_price as buy, pr.margin,
                (pr.unit_price * (1 + COALESCE(pr.margin,0)/100)) as "sellUnit",
                pr.total_buy_price as "buyTotal",
                (pr.qty * pr.unit_price * (1 + COALESCE(pr.margin,0)/100)) as "sellTotal",
                ((pr.qty * pr.unit_price * (1 + COALESCE(pr.margin,0)/100)) - pr.total_buy_price) as profit,
                COALESCE(pp.cgst, 0) as cgst, COALESCE(pp.sgst, 0) as sgst,
                COALESCE(pp.igst, 0) as igst,
                COALESCE(pp.total_with_gst, pr.total_buy_price) as "totalWithGST",
                pr.department as item_dept, ph.status
            FROM purchases_header ph
            JOIN products pr ON pr.purchase_id = ph.id
            LEFT JOIN parties pt ON pt.party_id = ph.party_id
            LEFT JOIN purchase_payments pp ON pp.purchase_id = ph.id
            WHERE ph.status = 'deleted'
            ORDER BY ph.date DESC, ph.id DESC, pr.product_id
            LIMIT ? OFFSET ?
        """, [int(limit), int(offset)]).fetchall()

    return jsonify({"entries": [dict(r) for r in rows], "total": total, "page": page, "limit": limit})
