"""Dashboard API — response shape matches the previous app's contract so
dashboard.js / dashboard.html keep working without field-name drift.
"""
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify

from core.db import get_conn
from core.accounting import VoucherEngine

import json

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/api/dashboard")
def get_dashboard_data():
    try:
        period = request.args.get("period", "today")
        with get_conn() as conn:

            # Keep purchases_header.status in sync with due dates before
            # reading any Credit/Partial/Overdue totals below.
            from routes.purchases import sync_overdue_purchase_statuses
            sync_overdue_purchase_statuses(conn)

            import core.dashboard_cache as dashboard_cache
            dashboard_cache.ensure_fresh(conn)

            def q1(sql, params=()):
                return conn.execute(sql, params).fetchone()

            def qall(sql, params=()):
                return conn.execute(sql, params).fetchall()

            # ── Category B: Period-Independent metrics (from 'alltime' row) ──
            alltime_row = q1("SELECT * FROM dashboard_data WHERE period = 'alltime'") or {}

            stock_summary = json.loads(alltime_row["stock_summary_json"]) if alltime_row and alltime_row.get("stock_summary_json") else {}
            low_stock_alerts = json.loads(alltime_row["low_stock_alerts_json"]) if alltime_row and alltime_row.get("low_stock_alerts_json") else []
            top_products = json.loads(alltime_row["top_products_json"]) if alltime_row and alltime_row.get("top_products_json") else []
            activities = json.loads(alltime_row["recent_activities_json"]) if alltime_row and alltime_row.get("recent_activities_json") else []
            sales_vs_purchase = json.loads(alltime_row["sales_vs_purchase_json"]) if alltime_row and alltime_row.get("sales_vs_purchase_json") else []
            monthly_profit = json.loads(alltime_row["monthly_profit_json"]) if alltime_row and alltime_row.get("monthly_profit_json") else []

            # ── totalReceivable / totalPayable / Stock from dashboard_data ──
            # Everything below is read from the cached 'alltime' row, which
            # apply_transaction_delta / refresh_financial_totals keep
            # up-to-date whenever anything changes in the app.
            total_receivable = float(alltime_row.get("total_receivable") or 0) if alltime_row else 0
            total_payable = float(alltime_row.get("total_payable") or 0) if alltime_row else 0
            total_qty = float(alltime_row.get("stock_qty") or 0) if alltime_row else 0
            total_inv_value = float(alltime_row.get("stock_value") or 0) if alltime_row else 0
            total_products = int(stock_summary.get("totalProducts", 0))
            low_stock_items = int(stock_summary.get("lowStockItems", 0))
            out_of_stock_items = int(stock_summary.get("outOfStockItems", 0))

            # ── Today business (always from cached 'today' row specifically) ─
            today_row = q1("SELECT * FROM dashboard_data WHERE period = 'today'") or {}
            today_purchase_count = int(today_row.get("purchase_count", 0)) if today_row else 0
            today_purchase_amount = float(today_row.get("period_purchases", 0)) if today_row else 0.0
            today_sales_count = int(today_row.get("sales_count", 0)) if today_row else 0
            today_sales_amount = float(today_row.get("period_sales", 0)) if today_row else 0.0

            # ── Category A: Period-Scoped metrics ───────────────────────
            if period != "custom":
                cache_row = q1("SELECT * FROM dashboard_data WHERE period = ?", (period,)) or {}
                period_sales = float(cache_row.get("period_sales", 0) or 0)
                period_purchases = float(cache_row.get("period_purchases", 0) or 0)
                period_profit = float(cache_row.get("period_profit", 0) or 0)
                period_cash_sales = float(cache_row.get("cash_sales", 0) or 0)
                period_credit_sales = float(cache_row.get("credit_sales", 0) or 0)
                period_credit_purchases = float(cache_row.get("credit_purchases", 0) or 0)

                recent_purchases = json.loads(cache_row["recent_purchases_json"]) if cache_row and cache_row.get("recent_purchases_json") else []
                recent_sales = json.loads(cache_row["recent_sales_json"]) if cache_row and cache_row.get("recent_sales_json") else []
                mode_dist = json.loads(cache_row["payment_mode_json"]) if cache_row and cache_row.get("payment_mode_json") else {}
                start_s = end_s = None
            else:
                from_date = request.args.get("from")
                to_date = request.args.get("to")
                if from_date and to_date:
                    start_date = datetime.strptime(from_date, "%Y-%m-%d").date()
                    end_date = datetime.strptime(to_date, "%Y-%m-%d").date()
                else:
                    start_date = end_date = datetime.now().date()
                start_s = str(start_date)
                end_s = str(end_date)

                period_sales = float(q1("""
                    SELECT COALESCE(SUM(total_sale_price), 0) AS t
                    FROM sales WHERE date >= ? AND date <= ?
                """, (start_s, end_s))["t"] or 0)

                period_purchases = float(q1("""
                    SELECT COALESCE(SUM(pp.total_with_gst), 0) AS t
                    FROM purchase_payments pp
                    JOIN purchases_header ph ON ph.id = pp.purchase_id
                    WHERE ph.date >= ? AND ph.date <= ?
                """, (start_s, end_s))["t"] or 0)

                period_profit = float(q1("""
                    SELECT COALESCE(SUM(total_profit), 0) AS t
                    FROM sales WHERE date >= ? AND date <= ?
                """, (start_s, end_s))["t"] or 0)

                period_cash_sales = float(q1("""
                    SELECT COALESCE(SUM(total_sale_price), 0) AS t
                    FROM sales
                    WHERE status = 'Cash' AND date >= ? AND date <= ?
                """, (start_s, end_s))["t"] or 0)

                period_credit_sales = float(q1("""
                    SELECT COALESCE(SUM(total_sale_price), 0) AS t
                    FROM sales
                    WHERE status IN ('Credit', 'Partial') AND date >= ? AND date <= ?
                """, (start_s, end_s))["t"] or 0)

                period_credit_purchases = float(q1("""
                    SELECT COALESCE(SUM(pp.total_with_gst), 0) AS t
                    FROM purchase_payments pp
                    JOIN purchases_header ph ON ph.id = pp.purchase_id
                    WHERE ph.status IN ('Credit', 'Partial', 'Overdue')
                      AND ph.date >= ? AND ph.date <= ?
                """, (start_s, end_s))["t"] or 0)

                recent_purchases = [
                    {
                        "date": str(r["date"] or ""),
                        "party": r["party"] or "",
                        "invoiceNo": r["invoice_no"] or "",
                        "buyTotal": float(r["total_buy"] or 0),
                    }
                    for r in qall("""
                        SELECT ph.date, pt.party_name AS party, ph.invoice_no,
                               pp.total_buy_amount AS total_buy
                        FROM purchases_header ph
                        LEFT JOIN parties pt ON pt.party_id = ph.party_id
                        LEFT JOIN purchase_payments pp ON pp.purchase_id = ph.id
                        WHERE ph.date >= ? AND ph.date <= ?
                        ORDER BY ph.id DESC
                        LIMIT 10
                    """, (start_s, end_s))
                ]

                recent_sales = [
                    {
                        "date": str(r["date"] or ""),
                        "customerName": r["customer_name"] or "",
                        "billNo": r["bill_no"] or "",
                        "sellTotal": float(r["total_sell"] or 0),
                        "paymentMode": r["payment_mode"] or "Cash",
                    }
                    for r in qall("""
                        SELECT s.date, c.customer_name, s.bill_no,
                               s.total_sale_price AS total_sell,
                               COALESCE(sp.mode_of_payment, s.status, 'Cash') AS payment_mode
                        FROM sales s
                        LEFT JOIN customers c ON c.customer_id = s.customers_id
                        LEFT JOIN sales_payments sp ON sp.sale_id = s.sale_id
                        WHERE s.date >= ? AND s.date <= ?
                        ORDER BY s.sale_id DESC
                        LIMIT 10
                    """, (start_s, end_s))
                ]

                mode_dist = {
                    (r["payment_mode"] or "Cash"): float(r["total"] or 0)
                    for r in qall("""
                        SELECT COALESCE(sp.mode_of_payment, s.status, 'Cash') AS payment_mode,
                               SUM(s.total_sale_price) AS total
                        FROM sales s
                        LEFT JOIN sales_payments sp ON sp.sale_id = s.sale_id
                        WHERE s.date >= ? AND s.date <= ?
                        GROUP BY 1
                    """, (start_s, end_s))
                }

            # ── Profit summary ──────────────────────────────────────────
            total_income = period_sales
            total_expenses = period_purchases
            gross_profit = period_profit
            net_profit = period_profit
            if period == "custom" and start_s and end_s:
                try:
                    pl = VoucherEngine.get_profit_loss(start_s, end_s)
                    if pl:
                        total_income = float(pl.get("total_income") or total_income)
                        total_expenses = float(pl.get("total_expenses") or total_expenses)
                        net_profit = float(pl.get("net_profit") or net_profit)
                except Exception:
                    pass

            return jsonify({
                "kpi": {
                    "periodSales": period_sales,
                    "periodPurchases": period_purchases,
                    "periodProfit": period_profit,
                    "cashSales": period_cash_sales,
                    "receivable": period_credit_sales,
                    "payable": period_credit_purchases,
                    "totalReceivable": total_receivable,
                    "totalPayable": total_payable,
                    "stockQty": total_qty,
                    "stockValue": total_inv_value,
                },
                "stockSummary": {
                    "totalProducts": total_products,
                    "totalQuantity": total_qty,
                    "totalValue": total_inv_value,
                    "lowStockItems": low_stock_items,
                    "outOfStockItems": out_of_stock_items,
                    "topSellingProduct": stock_summary.get("topSellingProduct", top_products[0]["name"] if top_products else "N/A"),
                },
                "profitSummary": {
                    "income": total_income,
                    "expenses": total_expenses,
                    "grossProfit": gross_profit,
                    "netProfit": net_profit,
                },
                "todayBusiness": {
                    "purchaseCount": today_purchase_count,
                    "purchaseAmount": today_purchase_amount,
                    "salesCount": today_sales_count,
                    "salesAmount": today_sales_amount,
                },
                "recentActivities": activities,
                "recentPurchases": recent_purchases,
                "recentSales": recent_sales,
                "lowStockAlerts": low_stock_alerts,
                "charts": {
                    "salesVsPurchase": sales_vs_purchase,
                    "monthlyProfit": monthly_profit,
                    "paymentModeDistribution": [
                        {"mode": k, "amount": v} for k, v in mode_dist.items()
                    ],
                },
                "topProducts": top_products,
            })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
