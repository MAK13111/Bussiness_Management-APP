import sqlite3
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify

from core.db import get_conn
from core.accounting import VoucherEngine

dashboard_bp = Blueprint("dashboard", __name__)

@dashboard_bp.route("/api/dashboard")
def get_dashboard_data():
    try:
        period = request.args.get('period', 'today')
        with get_conn() as conn:
            def get_date_range(period):
                today = datetime.now().date()
                if period == 'today':
                    return today, today
                elif period == 'week':
                    start = today - timedelta(days=today.weekday())
                    return start, today
                elif period == 'month':
                    start = today.replace(day=1)
                    return start, today
                else:
                    return None, None

            start_date, end_date = get_date_range(period)
            if period == 'custom':
                from_date = request.args.get('from')
                to_date = request.args.get('to')
                if from_date and to_date:
                    start_date = datetime.strptime(from_date, '%Y-%m-%d').date()
                    end_date = datetime.strptime(to_date, '%Y-%m-%d').date()
                else:
                    start_date = end_date = datetime.now().date()

            today = datetime.now().date()

            # NOTE: These helpers filter with a sargable range (col >= start AND
            # col < end+1day) instead of wrapping the column in date(...). Wrapping
            # the column (date(s.date) BETWEEN date(?) AND date(?)) defeats the
            # idx_sales_date/idx_purchases_date indexes and forces SQLite to do a
            # full table scan on every dashboard load -- with 100k+ rows in
            # sale_items/purchase_items this alone was the biggest source of the
            # "dashboard lags on open" slowness. Keeping the raw column bare lets
            # the planner use the index (SEARCH instead of SCAN).
            def sum_sales_amount(start, end):
                row = conn.execute("""
                    SELECT SUM(si.sell_total) as total
                    FROM sale_items si
                    JOIN sales s ON s.id = si.sale_id
                    WHERE s.date >= ? AND s.date < date(?, '+1 day')
                """, (start, end)).fetchone()
                return row['total'] or 0.0

            def sum_sales_profit(start, end):
                row = conn.execute("""
                    SELECT SUM(si.profit) as total
                    FROM sale_items si
                    JOIN sales s ON s.id = si.sale_id
                    WHERE s.date >= ? AND s.date < date(?, '+1 day')
                """, (start, end)).fetchone()
                return row['total'] or 0.0

            def sum_purchases(start, end):
                row = conn.execute("""
                    SELECT SUM(pi.buy_total) as total
                    FROM purchase_items pi
                    JOIN purchases p ON p.id = pi.purchase_id
                    WHERE p.date >= ? AND p.date < date(?, '+1 day')
                """, (start, end)).fetchone()
                return row['total'] or 0.0

            period_sales = sum_sales_amount(start_date, end_date)
            period_purchases = sum_purchases(start_date, end_date)
            period_profit = sum_sales_profit(start_date, end_date)

            def sum_sales_by_mode(start, end, mode):
                row = conn.execute("""
                    SELECT SUM(total_sell) as total
                    FROM sales
                    WHERE mode = ? AND date >= ? AND date < date(?, '+1 day')
                """, (mode, start, end)).fetchone()
                return row['total'] or 0.0

            def sum_purchases_by_mode(start, end, mode):
                row = conn.execute("""
                    SELECT SUM(total_buy) as total
                    FROM purchases
                    WHERE mode = ? AND date >= ? AND date < date(?, '+1 day')
                """, (mode, start, end)).fetchone()
                return row['total'] or 0.0

            # Cash Sales = cash-mode sales within the selected period
            period_cash_sales = sum_sales_by_mode(start_date, end_date, 'cash')
            # Credit Sales = new credit given within the selected period (period-based receivable)
            period_credit_sales = sum_sales_by_mode(start_date, end_date, 'credit')
            # Credit Purchases = new credit taken within the selected period (period-based payable)
            period_credit_purchases = sum_purchases_by_mode(start_date, end_date, 'credit')

            # Overall totals + stock value, computed in SQL instead of pulling every
            # purchase_items/sale_items row into Python and looping (was O(rows) per
            # dashboard load; at 1 lakh+ rows this alone caused most of the lag).
            row = conn.execute("""
                SELECT
                    COALESCE(SUM(buy_total), 0) as total_purchases,
                    COALESCE(SUM(qty - sold), 0) as total_stock_qty,
                    COALESCE(SUM(CASE WHEN qty > 0 THEN buy_total * (qty - sold) * 1.0 / qty ELSE 0 END), 0) as stock_value
                FROM purchase_items
            """).fetchone()
            total_purchases = row['total_purchases'] or 0.0
            total_stock_qty = row['total_stock_qty'] or 0
            stock_value = row['stock_value'] or 0.0

            row = conn.execute("""
                SELECT COALESCE(SUM(sell_total), 0) as total_sales,
                       COALESCE(SUM(profit), 0) as gross_profit
                FROM sale_items
            """).fetchone()
            total_sales = row['total_sales'] or 0.0
            gross_profit = row['gross_profit'] or 0.0

            # Stock Summary -- one GROUP BY query instead of one query per item (N+1).
            items = conn.execute("SELECT id, name, min_stock FROM items").fetchall()
            total_products = len(items)
            min_stock_by_name = {it['name']: (it['min_stock'] or 0) for it in items}

            stock_rows = conn.execute("""
                SELECT item,
                       SUM(CASE WHEN qty > 0 THEN qty - sold ELSE 0 END) as remaining,
                       SUM(CASE WHEN qty > 0 AND (qty - sold) > 0
                                THEN buy_total * (qty - sold) * 1.0 / qty ELSE 0 END) as inv_value
                FROM purchase_items
                GROUP BY item
            """).fetchall()

            total_qty = 0
            total_inv_value = 0.0
            low_stock_items = 0
            out_of_stock_items = 0
            low_stock_alerts = []
            seen_items = set()

            for r in stock_rows:
                item_name = r['item']
                seen_items.add(item_name)
                qty = r['remaining'] or 0
                inv_value = r['inv_value'] or 0.0
                if qty > 0:
                    total_qty += qty
                    total_inv_value += inv_value
                if qty <= 0:
                    out_of_stock_items += 1
                min_stock = min_stock_by_name.get(item_name, 0)
                if min_stock and qty < min_stock:
                    low_stock_items += 1
                    low_stock_alerts.append({'name': item_name, 'available': qty, 'min': min_stock})

            # Items master rows that have never had a purchase batch at all still count
            # as out-of-stock, same as before.
            for name in min_stock_by_name:
                if name not in seen_items:
                    out_of_stock_items += 1

            # Financial Summary from ledgers
            cash_balance = 0.0
            bank_balance = 0.0
            receivable = 0.0
            payable = 0.0
            gst_payable = 0.0

            engine = VoucherEngine()
            ledgers = conn.execute("SELECT id, name, group_id FROM ledgers").fetchall()
            for l in ledgers:
                bal = engine._get_ledger_balance(l['id'], None, conn)
                if l['name'] == 'Cash':
                    cash_balance = bal['balance'] if bal['balance_type'] == 'Debit' else -bal['balance']
                elif l['name'] == 'Bank Account':
                    bank_balance = bal['balance'] if bal['balance_type'] == 'Debit' else -bal['balance']
                elif l['name'] == 'GST Payable':
                    gst_payable = bal['balance'] if bal['balance_type'] == 'Credit' else -bal['balance']
                elif l['group_id']:
                    group = conn.execute("SELECT name FROM account_groups WHERE id=?", (l['group_id'],)).fetchone()
                    if group:
                        if group['name'] == 'Sundry Debtors':
                            receivable += bal['balance'] if bal['balance_type'] == 'Debit' else 0
                        elif group['name'] == 'Sundry Creditors':
                            payable += bal['balance'] if bal['balance_type'] == 'Credit' else 0

            # Profit Summary (current month)
            first_day = datetime.now().replace(day=1).strftime("%Y-%m-%d")
            today_str = datetime.now().strftime("%Y-%m-%d")
            # stock_value was already computed above from the same purchase_items
            # table -- pass it in so get_profit_loss doesn't re-run an identical
            # full-table aggregate just to get the same number again.
            pl = engine.get_profit_loss(first_day, today_str, closing_stock=stock_value)
            total_income = pl['total_income']
            total_expenses = pl['total_expenses']
            net_profit = pl['net_profit']

            # Top Selling Products -- one aggregate query, top 5 done in SQL
            # instead of pulling every sale_items row into a Python dict.
            rows = conn.execute("""
                SELECT COALESCE(item, 'Unknown') as item,
                       SUM(qty) as qty,
                       SUM(sell_total) as revenue
                FROM sale_items
                GROUP BY item
                ORDER BY revenue DESC
                LIMIT 5
            """).fetchall()
            top_products = [{'name': r['item'], 'qty': r['qty'] or 0, 'revenue': r['revenue'] or 0} for r in rows]

            # Recent Activities
            activities = []
            rows = conn.execute("""
                SELECT date, voucher_type, reference, narration
                FROM vouchers
                ORDER BY date DESC, id DESC
                LIMIT 10
            """).fetchall()
            for r in rows:
                activities.append({
                    'date': r['date'],
                    'type': r['voucher_type'],
                    'party': r['reference'] or '',
                    'amount': 0,
                    'status': 'Posted'
                })

            # Today's purchase/sale bill count + amount, computed directly in SQL.
            # (Previously the frontend derived this by filtering the 5-row
            # "recent purchases/sales" list to today's date -- which silently
            # undercounted whenever more than 5 bills happened today.)
            today_str_biz = today.strftime("%Y-%m-%d")
            row = conn.execute("""
                SELECT COUNT(*) as cnt, COALESCE(SUM(total_buy), 0) as total
                FROM purchases WHERE date >= ? AND date < date(?, '+1 day')
            """, (today_str_biz, today_str_biz)).fetchone()
            today_purchase_count, today_purchase_amount = row['cnt'], row['total']

            row = conn.execute("""
                SELECT COUNT(*) as cnt, COALESCE(SUM(total_sell), 0) as total
                FROM sales WHERE date >= ? AND date < date(?, '+1 day')
            """, (today_str_biz, today_str_biz)).fetchone()
            today_sales_count, today_sales_amount = row['cnt'], row['total']

            # Recent Purchases (within the selected period)
            rows = conn.execute("""
                SELECT date, party, invoice_no, total_buy
                FROM purchases
                WHERE date >= ? AND date < date(?, '+1 day')
                ORDER BY date DESC, id DESC
                LIMIT 5
            """, (start_date, end_date)).fetchall()
            # Keys camelCase me convert kiye (frontend invoiceNo/buyTotal expect karta hai,
            # DB column names invoice_no/total_buy hain — mismatch hi NaN/undefined ki wajah tha)
            recent_purchases = [{
                'date': r['date'],
                'party': r['party'],
                'invoiceNo': r['invoice_no'],
                'buyTotal': r['total_buy'] or 0
            } for r in rows]

            # Recent Sales (within the selected period)
            rows = conn.execute("""
                SELECT date, customer_name, bill_no, total_sell, payment_mode
                FROM sales
                WHERE date >= ? AND date < date(?, '+1 day')
                ORDER BY date DESC, id DESC
                LIMIT 5
            """, (start_date, end_date)).fetchall()
            recent_sales = [{
                'date': r['date'],
                'customerName': r['customer_name'],
                'billNo': r['bill_no'],
                'sellTotal': r['total_sell'] or 0,
                'paymentMode': r['payment_mode']
            } for r in rows]

            # Charts Data -- built with 2 GROUP BY queries total instead of
            # 7 (daily) + 12 (monthly) separate round trips that each fetched
            # and summed rows in Python.
            week_start_str = (today - timedelta(days=6)).strftime("%Y-%m-%d")
            today_str_chart = today.strftime("%Y-%m-%d")

            sales_by_day = {r['d']: r['total'] for r in conn.execute("""
                SELECT date(s.date) as d, SUM(si.sell_total) as total
                FROM sale_items si JOIN sales s ON s.id = si.sale_id
                WHERE s.date >= ? AND s.date < date(?, '+1 day')
                GROUP BY d
            """, (week_start_str, today_str_chart)).fetchall()}

            purchases_by_day = {r['d']: r['total'] for r in conn.execute("""
                SELECT date(p.date) as d, SUM(pi.buy_total) as total
                FROM purchase_items pi JOIN purchases p ON p.id = pi.purchase_id
                WHERE p.date >= ? AND p.date < date(?, '+1 day')
                GROUP BY d
            """, (week_start_str, today_str_chart)).fetchall()}

            sales_vs_purchase = []
            for i in range(6, -1, -1):
                d_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
                sales_vs_purchase.append({
                    'date': d_str,
                    'sales': sales_by_day.get(d_str, 0) or 0,
                    'purchases': purchases_by_day.get(d_str, 0) or 0
                })

            twelve_months_start = (today.replace(day=1) - timedelta(days=335)).strftime("%Y-%m-%d")
            profit_by_month = {r['ym']: r['profit'] for r in conn.execute("""
                SELECT strftime('%Y-%m', s.date) as ym, SUM(si.profit) as profit
                FROM sale_items si JOIN sales s ON s.id = si.sale_id
                WHERE s.date >= ?
                GROUP BY ym
            """, (twelve_months_start,)).fetchall()}

            monthly_profit = []
            for i in range(11, -1, -1):
                m = today - timedelta(days=30*i)
                ym_key = m.strftime("%Y-%m")
                monthly_profit.append({'month': m.strftime("%b"), 'profit': profit_by_month.get(ym_key, 0) or 0})

            # Payment mode distribution, scoped to the selected period instead of
            # scanning every sale ever placed on every dashboard load.
            mode_dist = {r['payment_mode'] or 'Cash': r['total'] or 0 for r in conn.execute("""
                SELECT payment_mode, SUM(total_sell) as total
                FROM sales
                WHERE date >= ? AND date < date(?, '+1 day')
                GROUP BY payment_mode
            """, (start_date, end_date)).fetchall()}

            return jsonify({
                'kpi': {
                    'periodSales': period_sales,
                    'periodPurchases': period_purchases,
                    'periodProfit': period_profit,
                    # Cash Sales / Credit Sales / Credit Purchases are period-based flows:
                    # how much happened during the selected period.
                    'cashInHand': period_cash_sales,
                    'receivable': period_credit_sales,
                    'payable': period_credit_purchases,
                    # Total Receivable / Total Payable are running ledger balances
                    # (see `financial` block below) — always as-of-now, not period based.
                    'totalReceivable': receivable,
                    'totalPayable': payable,
                    'stockQty': total_stock_qty,
                    'stockValue': stock_value
                },
                'stockSummary': {
                    'totalProducts': total_products,
                    'totalQuantity': total_qty,
                    'totalValue': total_inv_value,
                    'lowStockItems': low_stock_items,
                    'outOfStockItems': out_of_stock_items,
                    'topSellingProduct': top_products[0]['name'] if top_products else 'N/A'
                },
                'financial': {
                    'cash': cash_balance,
                    'bank': bank_balance,
                    'receivable': receivable,
                    'payable': payable,
                    'gstPayable': gst_payable
                },
                'profitSummary': {
                    'income': total_income,
                    'expenses': total_expenses,
                    'grossProfit': gross_profit,
                    'netProfit': net_profit
                },
                'todayBusiness': {
                    'purchaseCount': today_purchase_count,
                    'purchaseAmount': today_purchase_amount,
                    'salesCount': today_sales_count,
                    'salesAmount': today_sales_amount
                },
                'recentActivities': activities,
                'recentPurchases': recent_purchases,
                'recentSales': recent_sales,
                'lowStockAlerts': low_stock_alerts,
                'charts': {
                    'salesVsPurchase': sales_vs_purchase,
                    'monthlyProfit': monthly_profit,
                    'paymentModeDistribution': [{'mode': k, 'amount': v} for k, v in mode_dist.items()]
                },
                'topProducts': top_products
            })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
