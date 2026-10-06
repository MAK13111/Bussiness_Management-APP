"""Real-time cache management for dashboard KPI metrics and UI summaries stored in dashboard_data.
"""
from datetime import datetime, timedelta
import json


def get_period_bounds(period, today=None):
    """Return (start_date, end_date) as date objects for the given period.
    'alltime' and unknown periods return (None, None).
    """
    if today is None:
        today = datetime.now().date()
    elif isinstance(today, str):
        today = datetime.strptime(today.split(" ")[0], "%Y-%m-%d").date()

    if period == "today":
        return today, today
    if period == "week":
        return today - timedelta(days=today.weekday()), today
    if period == "month":
        return today.replace(day=1), today
    if period == "lastmonth":
        last_day_prev_month = today.replace(day=1) - timedelta(days=1)
        first_day_prev_month = last_day_prev_month.replace(day=1)
        return first_day_prev_month, last_day_prev_month
    return None, None


def recompute_period(conn, period):
    """Run period-scoped live queries for period and UPDATE the dashboard_data row.
    Uses conn.cursor() with %s placeholders (raw psycopg2).
    """
    cur = conn.cursor()
    start_date, end_date = get_period_bounds(period)
    start_s = str(start_date) if start_date else None
    end_s = str(end_date) if end_date else None

    if period == "alltime":
        cur.execute("SELECT COALESCE(SUM(total_sale_price), 0) AS t FROM sales")
        period_sales = float(cur.fetchone()["t"] or 0)

        cur.execute("""
            SELECT COALESCE(SUM(pp.total_with_gst), 0) AS t
            FROM purchase_payments pp
            JOIN purchases_header ph ON ph.id = pp.purchase_id
            WHERE ph.status != 'deleted'
        """)
        period_purchases = float(cur.fetchone()["t"] or 0)

        cur.execute("SELECT COALESCE(SUM(total_profit), 0) AS t FROM sales")
        period_profit = float(cur.fetchone()["t"] or 0)

        cur.execute("""
            SELECT COALESCE(SUM(total_sale_price), 0) AS t
            FROM sales WHERE status = 'Cash'
        """)
        cash_sales = float(cur.fetchone()["t"] or 0)

        cur.execute("""
            SELECT COALESCE(SUM(total_sale_price), 0) AS t
            FROM sales WHERE status IN ('Credit', 'Partial')
        """)
        credit_sales = float(cur.fetchone()["t"] or 0)

        cur.execute("""
            SELECT COALESCE(SUM(pp.total_with_gst), 0) AS t
            FROM purchase_payments pp
            JOIN purchases_header ph ON ph.id = pp.purchase_id
            WHERE ph.status IN ('Credit', 'Partial', 'Overdue') AND ph.status != 'deleted'
        """)
        credit_purchases = float(cur.fetchone()["t"] or 0)

        cur.execute("SELECT COUNT(*) AS c FROM purchases_header WHERE status != 'deleted'")
        purchase_count = int(cur.fetchone()["c"] or 0)

        cur.execute("SELECT COUNT(*) AS c FROM sales")
        sales_count = int(cur.fetchone()["c"] or 0)

        cur.execute("""
            SELECT ph.date, pt.party_name AS party, ph.invoice_no,
                   pp.total_buy_amount AS total_buy
            FROM purchases_header ph
            LEFT JOIN parties pt ON pt.party_id = ph.party_id
            LEFT JOIN purchase_payments pp ON pp.purchase_id = ph.id
            WHERE ph.status != 'deleted'
            ORDER BY ph.id DESC
            LIMIT 10
        """)
        recent_purchases = [
            {
                "date": str(r["date"] or ""),
                "party": r["party"] or "",
                "invoiceNo": r["invoice_no"] or "",
                "buyTotal": float(r["total_buy"] or 0),
            }
            for r in cur.fetchall()
        ]

        cur.execute("""
            SELECT s.date, c.customer_name, s.bill_no,
                   s.total_sale_price AS total_sell,
                   COALESCE(sp.mode_of_payment, s.status, 'Cash') AS payment_mode
            FROM sales s
            LEFT JOIN customers c ON c.customer_id = s.customers_id
            LEFT JOIN sales_payments sp ON sp.sale_id = s.sale_id
            ORDER BY s.sale_id DESC
            LIMIT 10
        """)
        recent_sales = [
            {
                "date": str(r["date"] or ""),
                "customerName": r["customer_name"] or "",
                "billNo": r["bill_no"] or "",
                "sellTotal": float(r["total_sell"] or 0),
                "paymentMode": r["payment_mode"] or "Cash",
            }
            for r in cur.fetchall()
        ]

        cur.execute("""
            SELECT COALESCE(sp.mode_of_payment, s.status, 'Cash') AS payment_mode,
                   SUM(s.total_sale_price) AS total
            FROM sales s
            LEFT JOIN sales_payments sp ON sp.sale_id = s.sale_id
            GROUP BY 1
        """)
        payment_mode_dist = {
            (r["payment_mode"] or "Cash"): float(r["total"] or 0)
            for r in cur.fetchall()
        }

    else:
        cur.execute("""
            SELECT COALESCE(SUM(total_sale_price), 0) AS t
            FROM sales WHERE date >= %s AND date <= %s
        """, (start_s, end_s))
        period_sales = float(cur.fetchone()["t"] or 0)

        cur.execute("""
            SELECT COALESCE(SUM(pp.total_with_gst), 0) AS t
            FROM purchase_payments pp
            JOIN purchases_header ph ON ph.id = pp.purchase_id
            WHERE ph.date >= %s AND ph.date <= %s AND ph.status != 'deleted'
        """, (start_s, end_s))
        period_purchases = float(cur.fetchone()["t"] or 0)

        cur.execute("""
            SELECT COALESCE(SUM(total_profit), 0) AS t
            FROM sales WHERE date >= %s AND date <= %s
        """, (start_s, end_s))
        period_profit = float(cur.fetchone()["t"] or 0)

        cur.execute("""
            SELECT COALESCE(SUM(total_sale_price), 0) AS t
            FROM sales
            WHERE status = 'Cash' AND date >= %s AND date <= %s
        """, (start_s, end_s))
        cash_sales = float(cur.fetchone()["t"] or 0)

        cur.execute("""
            SELECT COALESCE(SUM(total_sale_price), 0) AS t
            FROM sales
            WHERE status IN ('Credit', 'Partial') AND date >= %s AND date <= %s
        """, (start_s, end_s))
        credit_sales = float(cur.fetchone()["t"] or 0)

        cur.execute("""
            SELECT COALESCE(SUM(pp.total_with_gst), 0) AS t
            FROM purchase_payments pp
            JOIN purchases_header ph ON ph.id = pp.purchase_id
            WHERE ph.status IN ('Credit', 'Partial', 'Overdue') AND ph.status != 'deleted'
              AND ph.date >= %s AND ph.date <= %s
        """, (start_s, end_s))
        credit_purchases = float(cur.fetchone()["t"] or 0)

        cur.execute("""
            SELECT COUNT(*) AS c FROM purchases_header WHERE date >= %s AND date <= %s AND status != 'deleted'
        """, (start_s, end_s))
        purchase_count = int(cur.fetchone()["c"] or 0)

        cur.execute("""
            SELECT COUNT(*) AS c FROM sales WHERE date >= %s AND date <= %s
        """, (start_s, end_s))
        sales_count = int(cur.fetchone()["c"] or 0)

        cur.execute("""
            SELECT ph.date, pt.party_name AS party, ph.invoice_no,
                   pp.total_buy_amount AS total_buy
            FROM purchases_header ph
            LEFT JOIN parties pt ON pt.party_id = ph.party_id
            LEFT JOIN purchase_payments pp ON pp.purchase_id = ph.id
            WHERE ph.date >= %s AND ph.date <= %s AND ph.status != 'deleted'
            ORDER BY ph.id DESC
            LIMIT 10
        """, (start_s, end_s))
        recent_purchases = [
            {
                "date": str(r["date"] or ""),
                "party": r["party"] or "",
                "invoiceNo": r["invoice_no"] or "",
                "buyTotal": float(r["total_buy"] or 0),
            }
            for r in cur.fetchall()
        ]

        cur.execute("""
            SELECT s.date, c.customer_name, s.bill_no,
                   s.total_sale_price AS total_sell,
                   COALESCE(sp.mode_of_payment, s.status, 'Cash') AS payment_mode
            FROM sales s
            LEFT JOIN customers c ON c.customer_id = s.customers_id
            LEFT JOIN sales_payments sp ON sp.sale_id = s.sale_id
            WHERE s.date >= %s AND s.date <= %s
            ORDER BY s.sale_id DESC
            LIMIT 10
        """, (start_s, end_s))
        recent_sales = [
            {
                "date": str(r["date"] or ""),
                "customerName": r["customer_name"] or "",
                "billNo": r["bill_no"] or "",
                "sellTotal": float(r["total_sell"] or 0),
                "paymentMode": r["payment_mode"] or "Cash",
            }
            for r in cur.fetchall()
        ]


        cur.execute("""
            SELECT COALESCE(sp.mode_of_payment, s.status, 'Cash') AS payment_mode,
                   SUM(s.total_sale_price) AS total
            FROM sales s
            LEFT JOIN sales_payments sp ON sp.sale_id = s.sale_id
            WHERE s.date >= %s AND s.date <= %s
            GROUP BY 1
        """, (start_s, end_s))
        payment_mode_dist = {
            (r["payment_mode"] or "Cash"): float(r["total"] or 0)
            for r in cur.fetchall()
        }

    cur.execute("""
        UPDATE dashboard_data
        SET period_start = %s,
            period_end = %s,
            period_sales = %s,
            period_purchases = %s,
            period_profit = %s,
            cash_sales = %s,
            credit_sales = %s,
            credit_purchases = %s,
            purchase_count = %s,
            sales_count = %s,
            recent_purchases_json = %s,
            recent_sales_json = %s,
            payment_mode_json = %s,
            last_updated = CURRENT_TIMESTAMP
        WHERE period = %s
    """, (
        start_s, end_s, period_sales, period_purchases, period_profit,
        cash_sales, credit_sales, credit_purchases,
        purchase_count, sales_count,
        json.dumps(recent_purchases),
        json.dumps(recent_sales),
        json.dumps(payment_mode_dist),
        period
    ))


def recompute_global_snapshot(conn):
    """Compute period-independent (Category B) metrics and store them ONLY on the 'alltime' row."""
    from core.accounting import VoucherEngine

    cur = conn.cursor()
    today = datetime.now().date()
    today_s = str(today)

    # 1. Stock Summary & Low Stock Alerts
    cur.execute("""
        SELECT item_name AS item,
               COALESCE(SUM(CASE WHEN qty > 0 THEN qty - sold ELSE 0 END), 0) AS remaining,
               COALESCE(SUM(CASE WHEN qty > 0 AND (qty - sold) > 0
                   THEN total_buy_price * (qty - sold) / qty ELSE 0 END), 0) AS inv_value
        FROM products
        WHERE status != 'deleted'
        GROUP BY item_name
    """)
    stock_rows = cur.fetchall()

    cur.execute("SELECT name, min_stock FROM items")
    min_stock_by_name = {
        r["name"]: float(r["min_stock"] or 0) for r in cur.fetchall()
    }

    total_qty = 0.0
    total_inv_value = 0.0
    total_products = 0
    low_stock_items = 0
    out_of_stock_items = 0
    low_stock_alerts = []

    for r in stock_rows:
        total_products += 1
        item_name = r["item"]
        qty = float(r["remaining"] or 0)
        inv_value = float(r["inv_value"] or 0)
        if qty > 0:
            total_qty += qty
            total_inv_value += inv_value
        if qty <= 0:
            out_of_stock_items += 1
        min_stock = min_stock_by_name.get(item_name, 0)
        if min_stock and qty < min_stock:
            low_stock_items += 1
            low_stock_alerts.append({
                "name": item_name,
                "available": qty,
                "min": min_stock,
            })

    # 2. Top Selling Products
    cur.execute("""
        SELECT COALESCE(item_name, 'Unknown') AS item,
               SUM(quantity) AS qty,
               SUM(total_sale_price) AS revenue
        FROM sold_items
        WHERE COALESCE(is_return, 0) = 0
        GROUP BY item_name
        ORDER BY qty DESC
        LIMIT 5
    """)
    top_products = [
        {
            "name": r["item"],
            "qty": float(r["qty"] or 0),
            "revenue": float(r["revenue"] or 0),
        }
        for r in cur.fetchall()
    ]

    stock_summary = {
        "totalProducts": total_products,
        "totalQuantity": total_qty,
        "totalValue": total_inv_value,
        "lowStockItems": low_stock_items,
        "outOfStockItems": out_of_stock_items,
        "topSellingProduct": top_products[0]["name"] if top_products else "N/A",
    }

    # 2.5 Total Receivable / Payable from open bills (all-time, period-independent)
    # Use sp.remaining_amount — the authoritative column that already accounts for
    # any advance paid at billing time (avoids under-counting on partial-credit sales).
    cur.execute("""
        SELECT COALESCE(SUM(GREATEST(sp.remaining_amount, 0)), 0) AS t
        FROM sales s
        LEFT JOIN sales_payments sp ON sp.sale_id = s.sale_id
        WHERE s.status IN ('Credit', 'Partial')
    """)
    total_receivable = float(cur.fetchone()["t"] or 0)

    cur.execute("""
        SELECT COALESCE(SUM(pp.remaining_amount), 0) AS t
        FROM purchase_payments pp
        JOIN purchases_header ph ON ph.id = pp.purchase_id
        WHERE ph.status IN ('Credit', 'Partial', 'Overdue') AND ph.status != 'deleted'
    """)
    total_payable = float(cur.fetchone()["t"] or 0)

    # 3. Recent Activities (vouchers)
    cur.execute("""
        SELECT v.date, vt.code AS voucher_type, v.reference, v.narration
        FROM vouchers v
        LEFT JOIN voucher_types vt ON vt.id = v.voucher_type_id
        ORDER BY v.id DESC
        LIMIT 10
    """)
    activities = [
        {
            "date": str(r["date"] or ""),
            "type": r["voucher_type"] or "",
            "party": r["reference"] or "",
            "amount": 0,
            "status": "Posted",
        }
        for r in cur.fetchall()
    ]

    # 5. Charts: last 7 days sales vs purchases
    start_7d = str(today - timedelta(days=6))
    cur.execute("""
        SELECT date AS d, SUM(total_sale_price) AS t
        FROM sales
        WHERE date >= %s AND date <= %s
        GROUP BY date
    """, (start_7d, today_s))
    sales_by_day = {str(r["d"]): float(r["t"] or 0) for r in cur.fetchall()}

    cur.execute("""
        SELECT ph.date AS d, SUM(pp.total_buy_amount) AS t
        FROM purchase_payments pp
        JOIN purchases_header ph ON ph.id = pp.purchase_id
        WHERE ph.date >= %s AND ph.date <= %s AND ph.status != 'deleted'
        GROUP BY ph.date
    """, (start_7d, today_s))
    purchases_by_day = {str(r["d"]): float(r["t"] or 0) for r in cur.fetchall()}

    cur.execute("""
        SELECT ph.date AS d, SUM(pp.total_with_gst) AS t
        FROM purchase_payments pp
        JOIN purchases_header ph ON ph.id = pp.purchase_id
        WHERE ph.date >= %s AND ph.date <= %s AND ph.status != 'deleted'
        GROUP BY ph.date
    """, (start_7d, today_s))
    purchases_gst_by_day = {str(r["d"]): float(r["t"] or 0) for r in cur.fetchall()}

    sales_vs_purchase = []
    for i in range(6, -1, -1):
        d_str = str(today - timedelta(days=i))
        sales_vs_purchase.append({
            "date": d_str,
            "sales": sales_by_day.get(d_str, 0),
            "purchases": purchases_by_day.get(d_str, 0),
            "purchasesWithGst": purchases_gst_by_day.get(d_str, 0),
        })

    # 6. Charts: last 12 months profit
    twelve_start = (today.replace(day=1) - timedelta(days=335)).strftime("%Y-%m-%d")
    cur.execute("""
        SELECT TO_CHAR(date::date, 'YYYY-MM') AS ym,
               SUM(total_profit) AS profit
        FROM sales
        WHERE date >= %s
        GROUP BY ym
    """, (twelve_start,))
    profit_by_month = {r["ym"]: float(r["profit"] or 0) for r in cur.fetchall()}

    monthly_profit = []
    for i in range(11, -1, -1):
        m = today - timedelta(days=30 * i)
        ym_key = m.strftime("%Y-%m")
        monthly_profit.append({
            "month": m.strftime("%b"),
            "profit": profit_by_month.get(ym_key, 0),
        })

    cur.execute("""
        UPDATE dashboard_data
        SET stock_summary_json = %s,
            low_stock_alerts_json = %s,
            top_products_json = %s,
            recent_activities_json = %s,
            sales_vs_purchase_json = %s,
            monthly_profit_json = %s,
            total_receivable = %s,
            total_payable = %s,
            stock_qty = %s,
            stock_value = %s,
            last_updated = CURRENT_TIMESTAMP,
            snapshot_updated_at = CURRENT_TIMESTAMP
        WHERE period = 'alltime'
    """, (
        json.dumps(stock_summary),
        json.dumps(low_stock_alerts),
        json.dumps(top_products),
        json.dumps(activities),
        json.dumps(sales_vs_purchase),
        json.dumps(monthly_profit),
        total_receivable,
        total_payable,
        total_qty,
        total_inv_value,
    ))


def refresh_financial_totals(conn):
    """Recompute the four period-independent numeric columns on the 'alltime'
    row (total_receivable, total_payable, stock_qty, stock_value) directly
    from the live tables. Cheap aggregate queries -- safe to call at the end
    of any mutation and on every dashboard load.
    """
    cur = conn.cursor()

    # Use sp.remaining_amount — the authoritative column that already accounts for
    # any advance paid at billing time (avoids under-counting on partial-credit sales).
    cur.execute("""
        SELECT COALESCE(SUM(GREATEST(sp.remaining_amount, 0)), 0) AS t
        FROM sales s
        LEFT JOIN sales_payments sp ON sp.sale_id = s.sale_id
        WHERE s.status IN ('Credit', 'Partial')
    """)
    total_receivable = float(cur.fetchone()["t"] or 0)

    cur.execute("""
        SELECT COALESCE(SUM(pp.remaining_amount), 0) AS t
        FROM purchase_payments pp
        JOIN purchases_header ph ON ph.id = pp.purchase_id
        WHERE ph.status IN ('Credit', 'Partial', 'Overdue') AND ph.status != 'deleted'
    """)
    total_payable = float(cur.fetchone()["t"] or 0)

    cur.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN qty > 0 THEN qty - sold ELSE 0 END), 0) AS qty,
            COALESCE(SUM(CASE WHEN qty > 0 AND (qty - sold) > 0
                THEN total_buy_price * (qty - sold) / qty ELSE 0 END), 0) AS value
        FROM products
        WHERE status != 'deleted'
    """)
    stock_row = cur.fetchone()
    stock_qty = float(stock_row["qty"] or 0)
    stock_value = float(stock_row["value"] or 0)

    cur.execute("""
        UPDATE dashboard_data
        SET total_receivable = %s,
            total_payable = %s,
            stock_qty = %s,
            stock_value = %s,
            last_updated = CURRENT_TIMESTAMP
        WHERE period = 'alltime'
    """, (total_receivable, total_payable, stock_qty, stock_value))


def apply_stock_financial_delta(
    conn,
    stock_value_delta=0,
    stock_qty_delta=0,
    receivable_delta=0,
    payable_delta=0,
):
    """Incrementally adjust the 4 money-critical cached figures on the
    'alltime' dashboard_data row.  O(1) — no table scan.  Safe to call
    inside the same transaction as the write that caused the change.

    Raises on DB error — callers MUST NOT swallow the exception, because
    a failure here means the cached totals are now wrong.  The caller's
    transaction will roll back, keeping data and cache consistent.
    """
    cur = conn.cursor()
    cur.execute("""
        UPDATE dashboard_data
        SET stock_value      = stock_value      + %s,
            stock_qty        = stock_qty        + %s,
            total_receivable = total_receivable + %s,
            total_payable    = total_payable    + %s,
            last_updated     = CURRENT_TIMESTAMP
        WHERE period = 'alltime'
    """, (stock_value_delta, stock_qty_delta, receivable_delta, payable_delta))


SNAPSHOT_THROTTLE_SECONDS = 20


def recompute_all(conn):
    """Recompute cached KPI numbers and global snapshot."""
    for period in ["today", "week", "month", "lastmonth", "alltime"]:
        recompute_period(conn, period)
    recompute_global_snapshot(conn)


def ensure_fresh(conn):
    """Lazy rollover check for date-bound periods and snapshot checks for Category B."""
    cur = conn.cursor()
    cur.execute("SELECT period, period_start, period_end FROM dashboard_data")
    rows = {r["period"]: r for r in cur.fetchall()}

    for period in ["today", "week", "month", "lastmonth"]:
        exp_start, exp_end = get_period_bounds(period)
        exp_start_s = str(exp_start) if exp_start else None
        exp_end_s = str(exp_end) if exp_end else None

        r = rows.get(period)
        if not r or str(r.get("period_start") or "") != str(exp_start_s or "") or str(r.get("period_end") or "") != str(exp_end_s or ""):
            recompute_period(conn, period)

    cur.execute("""
        SELECT stock_summary_json,
               (snapshot_updated_at IS NULL OR snapshot_updated_at < NOW() - INTERVAL %s) AS stale
        FROM dashboard_data WHERE period = 'alltime'
    """, (f"{SNAPSHOT_THROTTLE_SECONDS} seconds",))
    r_alltime = cur.fetchone()
    if not r_alltime or not r_alltime.get("stock_summary_json") or r_alltime.get("stale"):
        recompute_global_snapshot(conn)

    # The four period-independent figures (stock_value, stock_qty,
    # total_receivable, total_payable) are kept current via incremental
    # apply_stock_financial_delta() calls inside every write path.
    # refresh_financial_totals() still runs via the async background
    # recompute path (_trigger_async_cache_recompute) as a drift-correction
    # safety net — we no longer need to fire the full products-table scan
    # on every dashboard load.


def apply_transaction_delta(
    conn, txn_date, sales_delta=0, purchases_delta=0, profit_delta=0,
    cash_sales_delta=0, credit_sales_delta=0, credit_purchases_delta=0,
    txn_type=None, recent_entry=None, payment_mode=None
):
    """Incrementally update cached KPIs/summaries for matching date range periods + 'alltime'."""
    txn_date_s = str(txn_date).split(" ")[0]
    cur = conn.cursor()

    cur.execute("""
        SELECT period, sales_count, purchase_count, recent_sales_json,
               recent_purchases_json, payment_mode_json
        FROM dashboard_data
        WHERE period = 'alltime'
           OR (period_start IS NOT NULL AND period_end IS NOT NULL
               AND %s::date >= period_start AND %s::date <= period_end)
    """, (txn_date_s, txn_date_s))
    matching_rows = cur.fetchall()

    for r in matching_rows:
        period = r["period"]
        cur.execute("""
            UPDATE dashboard_data
            SET period_sales = period_sales + %s,
                period_purchases = period_purchases + %s,
                period_profit = period_profit + %s,
                cash_sales = cash_sales + %s,
                credit_sales = credit_sales + %s,
                credit_purchases = credit_purchases + %s,
                last_updated = CURRENT_TIMESTAMP
            WHERE period = %s
        """, (
            sales_delta, purchases_delta, profit_delta,
            cash_sales_delta, credit_sales_delta, credit_purchases_delta,
            period
        ))

        if txn_type == "sale":
            sales_cnt = int(r["sales_count"] or 0) + 1
            recent_list = json.loads(r["recent_sales_json"]) if r.get("recent_sales_json") else []
            if recent_entry:
                recent_list.insert(0, recent_entry)
                recent_list = recent_list[:10]
            pm_dict = json.loads(r["payment_mode_json"]) if r.get("payment_mode_json") else {}
            if payment_mode:
                pm_dict[payment_mode] = float(pm_dict.get(payment_mode, 0) or 0) + float(sales_delta)

            cur.execute("""
                UPDATE dashboard_data
                SET sales_count = %s,
                    recent_sales_json = %s,
                    payment_mode_json = %s
                WHERE period = %s
            """, (sales_cnt, json.dumps(recent_list), json.dumps(pm_dict), period))

        elif txn_type == "purchase":
            purchase_cnt = int(r["purchase_count"] or 0) + 1
            recent_list = json.loads(r["recent_purchases_json"]) if r.get("recent_purchases_json") else []
            if recent_entry:
                recent_list.insert(0, recent_entry)
                recent_list = recent_list[:10]

            cur.execute("""
                UPDATE dashboard_data
                SET purchase_count = %s,
                    recent_purchases_json = %s
                WHERE period = %s
            """, (purchase_cnt, json.dumps(recent_list), period))


def adjust_recent_purchase_amount(conn, txn_date, invoice_no, amount_delta):
    """Reduce (or adjust) the buyTotal of an EXISTING recent_purchases_json
    entry, matched by invoiceNo, for every cached period covering txn_date.
    Used by purchase returns: unlike apply_transaction_delta's txn_type
    handling, this never inserts a new entry or bumps purchase_count --
    a return isn't a new purchase, it's a correction to an existing one.
    If the invoice isn't in a period's cached recent list (e.g. it has
    since been pushed out of the top-10), that period's list is left as-is.
    """
    if not invoice_no:
        return
    txn_date_s = str(txn_date).split(" ")[0]
    cur = conn.cursor()

    cur.execute("""
        SELECT period, recent_purchases_json
        FROM dashboard_data
        WHERE period = 'alltime'
           OR (period_start IS NOT NULL AND period_end IS NOT NULL
               AND %s::date >= period_start AND %s::date <= period_end)
    """, (txn_date_s, txn_date_s))
    matching_rows = cur.fetchall()

    for r in matching_rows:
        recent_list = json.loads(r["recent_purchases_json"]) if r.get("recent_purchases_json") else []
        changed = False
        for entry in recent_list:
            if entry.get("invoiceNo") == invoice_no:
                entry["buyTotal"] = max(0.0, float(entry.get("buyTotal") or 0) + amount_delta)
                changed = True
        if changed:
            cur.execute("""
                UPDATE dashboard_data
                SET recent_purchases_json = %s
                WHERE period = %s
            """, (json.dumps(recent_list), r["period"]))


def adjust_recent_sale_amount(conn, txn_date, bill_no, amount_delta):
    """Sales-return counterpart of adjust_recent_purchase_amount: reduce the
    sellTotal of an EXISTING recent_sales_json entry, matched by billNo, for
    every cached period covering txn_date. Never inserts a new entry or
    bumps sales_count -- a return isn't a new sale, it's a correction to an
    existing one. If the bill isn't in a period's cached recent list (e.g.
    pushed out of the top-10), that period's list is left as-is.
    """
    if not bill_no:
        return
    txn_date_s = str(txn_date).split(" ")[0]
    cur = conn.cursor()

    cur.execute("""
        SELECT period, recent_sales_json
        FROM dashboard_data
        WHERE period = 'alltime'
           OR (period_start IS NOT NULL AND period_end IS NOT NULL
               AND %s::date >= period_start AND %s::date <= period_end)
    """, (txn_date_s, txn_date_s))
    matching_rows = cur.fetchall()

    for r in matching_rows:
        recent_list = json.loads(r["recent_sales_json"]) if r.get("recent_sales_json") else []
        changed = False
        for entry in recent_list:
            if entry.get("billNo") == bill_no:
                entry["sellTotal"] = max(0.0, float(entry.get("sellTotal") or 0) + amount_delta)
                changed = True
        if changed:
            cur.execute("""
                UPDATE dashboard_data
                SET recent_sales_json = %s
                WHERE period = %s
            """, (json.dumps(recent_list), r["period"]))