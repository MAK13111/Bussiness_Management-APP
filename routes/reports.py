from datetime import datetime

from flask import Blueprint, request, jsonify

from core.db import get_conn
from core.calculations import profit_margin_pct
from routes.purchases import get_purchase_rows, get_purchase_rows_count
from routes.sales import get_sale_rows, get_sale_rows_count

reports_bp = Blueprint("reports", __name__)

@reports_bp.route("/api/reports/purchases", methods=["GET"])
def api_reports_purchases():
    filters = {
        'mode': request.args.get('mode'),
        'date_from': request.args.get('date_from'),
        'date_to': request.args.get('date_to'),
        'party': request.args.get('party'),
        'invoice_no': request.args.get('invoice_no'),
        'item': request.args.get('item'),
        'payment_type': request.args.get('payment_type'),
        'sort': request.args.get('sort', 'date_desc')
    }
    filters = {k: v for k, v in filters.items() if v is not None}

    # Pagination is opt-in: pass ?page=&limit= to avoid pulling every matching
    # row over the network. Without those params the response is unchanged
    # (plain list) for existing callers.
    page = request.args.get('page', type=int)
    limit = request.args.get('limit', type=int)
    if page and limit:
        offset = (page - 1) * limit
        rows = get_purchase_rows(filters, limit=limit, offset=offset)
        total = get_purchase_rows_count(filters)
        return jsonify({'entries': rows, 'total': total, 'page': page, 'limit': limit})

    rows = get_purchase_rows(filters)
    return jsonify(rows)

@reports_bp.route("/api/reports/sales", methods=["GET"])
def api_reports_sales():
    filters = {
        'mode': request.args.get('mode'),
        'date_from': request.args.get('date_from'),
        'date_to': request.args.get('date_to'),
        'customer': request.args.get('customer'),
        'bill_no': request.args.get('bill_no'),
        'item': request.args.get('item'),
        'payment_type': request.args.get('payment_type'),
        'sort': request.args.get('sort', 'date_desc')
    }
    filters = {k: v for k, v in filters.items() if v is not None}

    page = request.args.get('page', type=int)
    limit = request.args.get('limit', type=int)
    if page and limit:
        offset = (page - 1) * limit
        rows = get_sale_rows(filters, limit=limit, offset=offset)
        total = get_sale_rows_count(filters)
        return jsonify({'entries': rows, 'total': total, 'page': page, 'limit': limit})

    rows = get_sale_rows(filters)
    return jsonify(rows)

@reports_bp.route("/api/reports/replace_bills", methods=["GET"])
def api_reports_replace_bills():
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    party = request.args.get('party')
    bill_no = request.args.get('invoice_no') or request.args.get('bill_no')
    item = request.args.get('item')
    sort = request.args.get('sort', 'date_desc')

    query = "SELECT DISTINCT rb.* FROM replace_bills rb"
    conditions = []
    params = []

    if item:
        query += " JOIN replace_bill_items rbi ON rbi.replace_bill_id = rb.id"
        conditions.append("rbi.item LIKE ?")
        params.append(f"%{item}%")
    if date_from:
        conditions.append("rb.date >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("rb.date <= ?")
        params.append(date_to + " 23:59:59")
    if party:
        conditions.append("rb.customerName LIKE ?")
        params.append(f"%{party}%")
    if bill_no:
        conditions.append("rb.replaceBillNo LIKE ?")
        params.append(f"%{bill_no}%")

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY rb.date " + ("ASC" if sort == 'date_asc' else "DESC")

    with get_conn() as conn:
        headers = conn.execute(query, params).fetchall()
        result = [dict(h) for h in headers]
        header_ids = [h["id"] for h in result]

        # Single query for all items instead of one query per header (N+1).
        items_by_bill = {}
        if header_ids:
            placeholders = ",".join("?" for _ in header_ids)
            item_rows = conn.execute(f"""
                SELECT replace_bill_id, side, item, size, qty, sell_price, sell_total
                FROM replace_bill_items
                WHERE replace_bill_id IN ({placeholders})
            """, header_ids).fetchall()
            for i in item_rows:
                i = dict(i)
                items_by_bill.setdefault(i["replace_bill_id"], []).append(i)

        for h in result:
            h["items"] = items_by_bill.get(h["id"], [])
    return jsonify(result)

@reports_bp.route("/api/reports/monthly", methods=["GET"])
def api_reports_monthly():
    year = request.args.get('year', str(datetime.now().year))

    with get_conn() as conn:
        purchase_rows = conn.execute("""
            SELECT strftime('%m', date) as m, COALESCE(SUM(total_buy), 0) as total
            FROM purchases
            WHERE strftime('%Y', date) = ?
            GROUP BY m
        """, (year,)).fetchall()

        sales_rows = conn.execute("""
            SELECT strftime('%m', date) as m,
                   COALESCE(SUM(total_sell), 0) as sales,
                   COALESCE(SUM(total_profit), 0) as profit
            FROM sales
            WHERE strftime('%Y', date) = ?
            GROUP BY m
        """, (year,)).fetchall()

        items_rows = conn.execute("""
            SELECT strftime('%m', s.date) as m, COALESCE(SUM(si.qty), 0) as qty
            FROM sale_items si
            JOIN sales s ON si.sale_id = s.id
            WHERE strftime('%Y', s.date) = ?
            GROUP BY m
        """, (year,)).fetchall()

    purchase_map = {r['m']: r['total'] for r in purchase_rows}
    sales_map = {r['m']: (r['sales'], r['profit']) for r in sales_rows}
    items_map = {r['m']: r['qty'] for r in items_rows}

    month_names = ['January', 'February', 'March', 'April', 'May', 'June',
                   'July', 'August', 'September', 'October', 'November', 'December']

    result = []
    for i in range(1, 13):
        mkey = f"{i:02d}"
        sales_val, profit_val = sales_map.get(mkey, (0, 0))
        result.append({
            "month": month_names[i - 1],
            "purchases": purchase_map.get(mkey, 0),
            "sales": sales_val,
            "profit": profit_val,
            "itemsSold": items_map.get(mkey, 0)
        })

    return jsonify(result)

@reports_bp.route("/api/reports/profit", methods=["GET"])
def api_reports_profit():
    date_from = request.args.get('from', '')
    date_to = request.args.get('to', '')

    # If no range is given, default to the current month instead of fetching
    # every sale_items row ever recorded (unbounded at 1 lakh+ rows).
    if not date_from and not date_to:
        date_from = datetime.now().replace(day=1).strftime('%Y-%m-%d')
        date_to = datetime.now().strftime('%Y-%m-%d')

    where_clause = "WHERE 1=1"
    params = []
    if date_from:
        where_clause += " AND s.date >= ?"
        params.append(date_from)
    if date_to:
        where_clause += " AND s.date <= ?"
        params.append(date_to)

    query = f"""
        SELECT s.date as date, s.customer_name as party, si.item as item, si.qty as qty,
               si.buy_total as buyTotal, si.sell_total as sellTotal, si.profit as profit
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.id
        {where_clause}
        ORDER BY s.date ASC, si.id DESC
    """

    # Totals computed in SQL (SUM) so the response's grand totals don't depend
    # on Python summing the same rows we already fetched for the entries list.
    totals_query = f"""
        SELECT COALESCE(SUM(si.buy_total),0) as purchases,
               COALESCE(SUM(si.sell_total),0) as sales,
               COALESCE(SUM(si.profit),0) as profit
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.id
        {where_clause}
    """

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        totals_row = conn.execute(totals_query, params).fetchone()

    entries = [dict(r) for r in rows]
    totals = {
        "purchases": totals_row["purchases"] or 0,
        "sales": totals_row["sales"] or 0,
        "profit": totals_row["profit"] or 0,
        # Was computed client-side in reports/profit.js; now the API supplies
        # it directly so the frontend only renders, doesn't calculate.
        "marginPct": profit_margin_pct(totals_row["profit"], totals_row["sales"])
    }
    return jsonify({"entries": entries, "totals": totals})
