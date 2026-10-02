"""Real-time cache for Reports:
1. reports_stats_cache (Analyze-initial stats: 'all' / 'cash' / 'credit')
2. monthly_stats_cache (Monthly breakdown: purchases, sales, profit, items_sold per year/month)
3. daily_profit_cache (Daily profit report aggregates: item_count, qty, buy_total, sell_total, profit)

Mirrors dashboard_cache.py's pattern:
- apply_purchase_delta() / apply_sale_delta() incrementally update counters
  the instant a new bill is created (cheap, called inside the same transaction).
- recompute_all() does a full rebuild from live tables for edits, returns,
  and replacements.
"""

from datetime import datetime


def _mode_for_status(status):
    """Map a purchase/sale bill status to the cached mode bucket -- matches
    the mode filter in routes/reports.py's _purchase_query_parts /
    _sale_query_parts (both treat anything that isn't plain 'Cash' as the
    'credit' bucket)."""
    return "cash" if (status or "").strip() == "Cash" else "credit"


def _parse_date_parts(date_str):
    if not date_str:
        now = datetime.now()
        return now.year, now.month, now.strftime("%Y-%m-%d")
    s = str(date_str).split(" ")[0].strip()
    try:
        dt = datetime.strptime(s, "%Y-%m-%d")
        return dt.year, dt.month, s
    except Exception:
        now = datetime.now()
        return now.year, now.month, now.strftime("%Y-%m-%d")


def recompute_mode(conn, mode):
    """Run aggregate queries for analyze-initial for one mode, and UPDATE reports_stats_cache."""
    cur = conn.cursor()

    pur_where = ""
    if mode == "cash":
        pur_where = "AND ph.status = 'Cash'"
    elif mode == "credit":
        pur_where = "AND ph.status IN ('Credit','Partial','Paid','Overdue')"

    cur.execute(f"""
        SELECT COUNT(pr.product_id) as total_entries,
               COALESCE(SUM(pr.qty), 0) as total_qty,
               COALESCE(SUM(pr.total_buy_price), 0) as total_purchase,
               COALESCE(SUM(pr.qty * pr.unit_price * (1 + COALESCE(pr.margin,0)/100)), 0) as total_sell,
               COALESCE(SUM((pr.qty * pr.unit_price * (1 + COALESCE(pr.margin,0)/100)) - pr.total_buy_price), 0) as total_profit
        FROM purchases_header ph
        JOIN products pr ON pr.purchase_id = ph.id
        WHERE ph.status != 'deleted' {pur_where}
    """)
    pur = cur.fetchone()

    sal_where = ""
    if mode == "cash":
        sal_where = "AND s.status = 'Cash'"
    elif mode == "credit":
        sal_where = "AND s.status IN ('Credit','Partial','Paid')"

    cur.execute(f"""
        SELECT COUNT(si.sold_item_id) as total_sells,
               COALESCE(SUM(si.quantity), 0) as total_qty,
               COALESCE(SUM(si.total_buy_price), 0) as total_cost,
               COALESCE(SUM(si.total_sale_price), 0) as total_sell_amt,
               COALESCE(SUM(si.total_sale_price - si.total_buy_price), 0) as total_profit
        FROM sales s
        JOIN sold_items si ON si.sale_id = s.sale_id
        WHERE COALESCE(si.is_return, 0) = 0 {sal_where}
    """)
    sal = cur.fetchone()

    cur.execute("""
        UPDATE reports_stats_cache
        SET purchase_count = %s, purchase_qty = %s, purchase_buy_total = %s,
            purchase_sell_total = %s, purchase_profit = %s,
            sale_count = %s, sale_qty = %s, sale_cost_total = %s,
            sale_sell_total = %s, sale_profit = %s,
            last_updated = CURRENT_TIMESTAMP
        WHERE mode = %s
    """, (
        int(pur["total_entries"] or 0), float(pur["total_qty"] or 0),
        float(pur["total_purchase"] or 0), float(pur["total_sell"] or 0), float(pur["total_profit"] or 0),
        int(sal["total_sells"] or 0), float(sal["total_qty"] or 0),
        float(sal["total_cost"] or 0), float(sal["total_sell_amt"] or 0), float(sal["total_profit"] or 0),
        mode,
    ))


def recompute_monthly_stats(conn, year=None):
    """Rebuild monthly_stats_cache table for a given year or all years."""
    cur = conn.cursor()
    if year:
        cur.execute("DELETE FROM monthly_stats_cache WHERE year = %s", (year,))
        year_where_pur = "WHERE ph.date >= %s AND ph.date < %s AND ph.status != 'deleted'"
        year_where_sal = "WHERE s.date >= %s AND s.date < %s"
        p_args = (f"{year}-01-01", f"{year + 1}-01-01")
    else:
        cur.execute("TRUNCATE TABLE monthly_stats_cache")
        year_where_pur = "WHERE ph.status != 'deleted'"
        year_where_sal = "WHERE 1=1"
        p_args = ()

    # Purchases by year, month
    cur.execute(f"""
        SELECT EXTRACT(YEAR FROM ph.date)::INT AS yr,
               EXTRACT(MONTH FROM ph.date)::INT AS mth,
               COALESCE(SUM(pp.total_buy_amount), 0) AS purchases
        FROM purchase_payments pp
        JOIN purchases_header ph ON ph.id = pp.purchase_id
        {year_where_pur}
        GROUP BY EXTRACT(YEAR FROM ph.date), EXTRACT(MONTH FROM ph.date)
    """, p_args)

    pur_rows = cur.fetchall()
    pur_map = {(r["yr"], r["mth"]): float(r["purchases"]) for r in pur_rows}

    # Sales by year, month
    cur.execute(f"""
        SELECT EXTRACT(YEAR FROM s.date)::INT AS yr,
               EXTRACT(MONTH FROM s.date)::INT AS mth,
               COALESCE(SUM(s.total_sale_price), 0) AS sales,
               COALESCE(SUM(s.total_profit), 0) AS profit,
               COALESCE(SUM(si.quantity), 0) AS items_sold
        FROM sales s
        LEFT JOIN sold_items si ON si.sale_id = s.sale_id
        {year_where_sal}
        GROUP BY EXTRACT(YEAR FROM s.date), EXTRACT(MONTH FROM s.date)
    """, p_args)
    sal_rows = cur.fetchall()
    sal_map = {(r["yr"], r["mth"]): {
        "sales": float(r["sales"]),
        "profit": float(r["profit"]),
        "items_sold": float(r["items_sold"]),
    } for r in sal_rows}

    all_keys = set(pur_map.keys()) | set(sal_map.keys())
    if year:
        all_keys.update((year, m) for m in range(1, 13))

    for yr, mth in all_keys:
        if not yr or not mth:
            continue
        p_amt = pur_map.get((yr, mth), 0.0)
        s_info = sal_map.get((yr, mth), {"sales": 0.0, "profit": 0.0, "items_sold": 0.0})
        cur.execute("""
            INSERT INTO monthly_stats_cache (year, month, purchases, sales, profit, items_sold, last_updated)
            VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (year, month) DO UPDATE SET
                purchases = EXCLUDED.purchases,
                sales = EXCLUDED.sales,
                profit = EXCLUDED.profit,
                items_sold = EXCLUDED.items_sold,
                last_updated = CURRENT_TIMESTAMP
        """, (yr, mth, p_amt, s_info["sales"], s_info["profit"], s_info["items_sold"]))


def recompute_daily_profit(conn):
    """Rebuild daily_profit_cache table from live sales & sold_items."""
    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE daily_profit_cache")
    cur.execute("""
        INSERT INTO daily_profit_cache (sale_date, item_count, qty_sold, buy_total, sell_total, profit, last_updated)
        SELECT s.date as sale_date,
               COUNT(si.sold_item_id) as item_count,
               COALESCE(SUM(si.quantity), 0) as qty_sold,
               COALESCE(SUM(si.total_buy_price), 0) as buy_total,
               COALESCE(SUM(si.total_sale_price), 0) as sell_total,
               COALESCE(SUM(si.total_sale_price - si.total_buy_price), 0) as profit,
               CURRENT_TIMESTAMP
        FROM sales s
        JOIN sold_items si ON si.sale_id = s.sale_id
        WHERE COALESCE(si.is_return, 0) = 0
        GROUP BY s.date
    """)


def recompute_all(conn):
    """Full rebuild of all cache tables. Used after edits/returns where
    an incremental delta can't be safely derived."""
    for mode in ("all", "cash", "credit"):
        recompute_mode(conn, mode)
    recompute_monthly_stats(conn)
    recompute_daily_profit(conn)


def get_stats(conn, mode):
    """Read cached analyze-initial row for a mode ('all'/'cash'/'credit')."""
    cur = conn.cursor()
    cur.execute("SELECT * FROM reports_stats_cache WHERE mode = %s", (mode,))
    row = cur.fetchone()
    if not row:
        recompute_mode(conn, mode)
        cur.execute("SELECT * FROM reports_stats_cache WHERE mode = %s", (mode,))
        row = cur.fetchone()
    return row


def get_monthly_stats(conn, year):
    """Read 12 monthly rows for a given year from monthly_stats_cache."""
    cur = conn.cursor()
    cur.execute("SELECT * FROM monthly_stats_cache WHERE year = %s ORDER BY month", (year,))
    rows = cur.fetchall()
    if not rows:
        recompute_monthly_stats(conn, year)
        cur.execute("SELECT * FROM monthly_stats_cache WHERE year = %s ORDER BY month", (year,))
        rows = cur.fetchall()

    m_map = {r["month"]: r for r in rows}
    res = []
    for m in range(1, 13):
        r = m_map.get(m)
        res.append({
            "month": m,
            "purchases": float(r["purchases"]) if r else 0.0,
            "sales": float(r["sales"]) if r else 0.0,
            "profit": float(r["profit"]) if r else 0.0,
            "itemsSold": float(r["items_sold"]) if r else 0.0,
        })
    return res


def get_profit_report_totals(conn, date_from=None, date_to=None):
    """Get profit report aggregate totals instantly from cache tables."""
    cur = conn.cursor()

    if not date_from and not date_to:
        stats = get_stats(conn, "all")
        t_buy = float(stats["sale_cost_total"] or 0)
        t_sales = float(stats["sale_sell_total"] or 0)
        t_profit = float(stats["sale_profit"] or 0)
        t_count = int(stats["sale_count"] or 0)
    else:
        where = "WHERE 1=1"
        params = []
        if date_from:
            where += " AND sale_date >= %s"
            params.append(date_from)
        if date_to:
            where += " AND sale_date <= %s"
            params.append(date_to)

        cur.execute(f"""
            SELECT COALESCE(SUM(item_count), 0) AS c,
                   COALESCE(SUM(buy_total), 0) AS b,
                   COALESCE(SUM(sell_total), 0) AS s,
                   COALESCE(SUM(profit), 0) AS p
            FROM daily_profit_cache
            {where}
        """, params)
        row = cur.fetchone()
        t_count = int(row["c"] or 0)
        t_buy = float(row["b"] or 0)
        t_sales = float(row["s"] or 0)
        t_profit = float(row["p"] or 0)

    margin = (t_profit / t_sales * 100) if t_sales else 0
    return {
        "purchases": t_buy,
        "sales": t_sales,
        "profit": t_profit,
        "marginPct": round(margin, 2),
        "total_rows": t_count,
    }


def apply_purchase_delta(conn, bill_status, count_delta, qty_delta, buy_delta, sell_delta, profit_delta, bill_date=None, total_buy_amount=None):
    """Incrementally add a newly-created purchase bill's totals."""
    mode = _mode_for_status(bill_status)
    cur = conn.cursor()
    cur.execute("""
        UPDATE reports_stats_cache
        SET purchase_count = purchase_count + %s,
            purchase_qty = purchase_qty + %s,
            purchase_buy_total = purchase_buy_total + %s,
            purchase_sell_total = purchase_sell_total + %s,
            purchase_profit = purchase_profit + %s,
            last_updated = CURRENT_TIMESTAMP
        WHERE mode IN ('all', %s)
    """, (count_delta, qty_delta, buy_delta, sell_delta, profit_delta, mode))

    if bill_date:
        yr, mth, _ = _parse_date_parts(bill_date)
        p_val = total_buy_amount if total_buy_amount is not None else buy_delta
        cur.execute("""
            INSERT INTO monthly_stats_cache (year, month, purchases, sales, profit, items_sold, last_updated)
            VALUES (%s, %s, %s, 0, 0, 0, CURRENT_TIMESTAMP)
            ON CONFLICT (year, month) DO UPDATE SET
                purchases = monthly_stats_cache.purchases + EXCLUDED.purchases,
                last_updated = CURRENT_TIMESTAMP
        """, (yr, mth, p_val))


def apply_sale_delta(conn, bill_status, count_delta, qty_delta, cost_delta, sell_delta, profit_delta, bill_date=None):
    """Incrementally add a newly-created sale bill's totals."""
    mode = _mode_for_status(bill_status)
    cur = conn.cursor()
    cur.execute("""
        UPDATE reports_stats_cache
        SET sale_count = sale_count + %s,
            sale_qty = sale_qty + %s,
            sale_cost_total = sale_cost_total + %s,
            sale_sell_total = sale_sell_total + %s,
            sale_profit = sale_profit + %s,
            last_updated = CURRENT_TIMESTAMP
        WHERE mode IN ('all', %s)
    """, (count_delta, qty_delta, cost_delta, sell_delta, profit_delta, mode))

    if bill_date:
        yr, mth, d_str = _parse_date_parts(bill_date)
        # Update monthly stats cache
        cur.execute("""
            INSERT INTO monthly_stats_cache (year, month, purchases, sales, profit, items_sold, last_updated)
            VALUES (%s, %s, 0, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (year, month) DO UPDATE SET
                sales = monthly_stats_cache.sales + EXCLUDED.sales,
                profit = monthly_stats_cache.profit + EXCLUDED.profit,
                items_sold = monthly_stats_cache.items_sold + EXCLUDED.items_sold,
                last_updated = CURRENT_TIMESTAMP
        """, (yr, mth, sell_delta, profit_delta, qty_delta))

        # Update daily profit cache
        cur.execute("""
            INSERT INTO daily_profit_cache (sale_date, item_count, qty_sold, buy_total, sell_total, profit, last_updated)
            VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (sale_date) DO UPDATE SET
                item_count = daily_profit_cache.item_count + EXCLUDED.item_count,
                qty_sold = daily_profit_cache.qty_sold + EXCLUDED.qty_sold,
                buy_total = daily_profit_cache.buy_total + EXCLUDED.buy_total,
                sell_total = daily_profit_cache.sell_total + EXCLUDED.sell_total,
                profit = daily_profit_cache.profit + EXCLUDED.profit,
                last_updated = CURRENT_TIMESTAMP
        """, (d_str, count_delta, qty_delta, cost_delta, sell_delta, profit_delta))
