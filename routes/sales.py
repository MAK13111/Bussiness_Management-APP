from datetime import datetime
import threading

from flask import Blueprint, request, jsonify
import core.dashboard_cache as dashboard_cache
from core.db import get_conn
from core.shared_helpers import to_camel_row, get_or_create_ledger, round2
from core.accounting import VoucherEngine

sales_bp = Blueprint("sales", __name__)


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


def create_sale_bill(header_data, items, mode):
    with get_conn() as conn:
        is_credit = (mode or '').lower() == 'credit'
        bill_status = 'Credit' if is_credit else 'Cash'
        date_str = header_data.get('date', datetime.now().strftime("%Y-%m-%d"))
        if " " in str(date_str):
            date_str = str(date_str).split(" ")[0]

        customer_name = (header_data.get('customer_name') or '').strip()
        customer_no = (header_data.get('customer_no') or '').strip()
        cust_status = 1 if is_credit else 0

        if customer_name or customer_no:
            cust = conn.execute(
                "SELECT customer_id FROM customers WHERE LOWER(customer_name) = LOWER(?) AND COALESCE(customer_no,'') = ?",
                (customer_name, customer_no)
            ).fetchone()
            if cust:
                customer_id = cust["customer_id"]
                if is_credit:
                    conn.execute("UPDATE customers SET status = 1 WHERE customer_id = ?", (customer_id,))
            else:
                cur_c = conn.execute(
                    "INSERT INTO customers (customer_name, customer_no, status) VALUES (?, ?, ?)",
                    (customer_name or 'Walk-in', customer_no, cust_status)
                )
                customer_id = cur_c.lastrowid
        else:
            # No customer details entered at all — don't save a customer
            # record for this sale, leave it unlinked instead.
            customer_id = None

        discount_precise = float(header_data.get('discount', 0) or 0)
        discount = round2(discount_precise)
        due_date = header_data.get('due_date') or None

        cur = conn.execute("""
            INSERT INTO sales
            (customers_id, status, bill_no, date, due_date, total_buy_price, total_sale_price,
             total_profit, discount, created_at)
            VALUES (?, ?, ?, ?, ?, 0, 0, 0, ?, ?)
        """, (
            customer_id, bill_status, header_data.get('bill_no', '') or None,
            date_str, due_date, discount,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        sale_id = cur.lastrowid

        total_sell = 0.0
        total_buy = 0.0
        total_profit = 0.0

        processed_items = []
        for item in items:
            qty = float(item.get('qty', 1))
            buy_price = float(item.get('buy_price', 0))
            margin = float(item.get('margin', 0))
            actual_sell_price = float(item.get('sell_price', 0) or 0)
            raw_unit_price = actual_sell_price if actual_sell_price > 0 else buy_price * (1 + margin / 100)
            raw_line_total = round2(raw_unit_price * qty)
            buy_total = qty * buy_price

            # ── OLD DATA ITEM ─────────────────────────────────────────────────
            # Items sourced from the legacy old_data table (imported from xlsx).
            is_old_item = bool(item.get('is_old_data'))
            old_data_id = item.get('old_data_id') or item.get('purchase_item_id')
            old_uniqee_id = item.get('uniqee_id')

            # Fallback detection if is_old_data flag was not explicitly sent
            if not is_old_item and item.get('code') and not item.get('purchase_item_id'):
                code_str = str(item.get('code')).strip()
                od_check = conn.execute(
                    "SELECT id, uniqee_id FROM old_data WHERE LOWER(TRIM(item_code)) = LOWER(TRIM(?)) LIMIT 1",
                    (code_str,)
                ).fetchone()
                if od_check:
                    is_old_item = True
                    old_data_id = od_check['id']
                    old_uniqee_id = od_check['uniqee_id']

            if is_old_item:
                if old_data_id:
                    try:
                        # Fetch uniqee_id from old_data if not already present
                        if old_uniqee_id is None:
                            od_row = conn.execute(
                                "SELECT uniqee_id FROM old_data WHERE id = ?",
                                (int(old_data_id),)
                            ).fetchone()
                            if od_row and od_row["uniqee_id"] is not None:
                                old_uniqee_id = od_row["uniqee_id"]

                        conn.execute("""
                            UPDATE old_data
                            SET remaining = remaining - ?,
                                sold      = sold + ?
                            WHERE id = ?
                        """, (qty, qty, int(old_data_id)))
                    except Exception as _oe:
                        print(f"[old_data] stock update error: {_oe}")

                line_total_override_raw = item.get('line_total_override')
                line_total_override = (
                    round2(float(line_total_override_raw))
                    if line_total_override_raw not in (None, '')
                    else None
                )
                processed_items.append({
                    "item": item, "qty": qty, "buy_price": buy_price, "margin": margin,
                    "buy_total": buy_total, "raw_line_total": raw_line_total,
                    "product_id": old_uniqee_id,       # store old_data uniqee_id in product_id
                    "resolved_codes": [],              # no barcodes for old_data items
                    "line_total_override": line_total_override,
                    "is_old_data": True,
                })
                continue
            # ── END OLD DATA ITEM ─────────────────────────────────────────────

            scanned_codes_list = item.get('scanned_codes') or []
            if not scanned_codes_list and item.get('code'):
                scanned_codes_list = [item.get('code')]

            product_id = item.get('purchase_item_id')
            resolved_codes = []
            for bc_code in scanned_codes_list:
                try:
                    code_int = int(str(bc_code).strip())
                except (TypeError, ValueError):
                    continue
                pi = conn.execute("""
                    SELECT id, product_id, is_available, is_returned
                    FROM purchase_item
                    WHERE barcode_no = ? AND product_id IS NOT NULL
                """, (code_int,)).fetchone()
                if not pi or pi["is_returned"]:
                    continue
                if product_id is None:
                    product_id = pi["product_id"]
                resolved_codes.append(code_int)

            for code_int in resolved_codes:
                conn.execute("""
                    UPDATE purchase_item
                    SET is_available = 'sold', sold_at = ?
                    WHERE barcode_no = ?
                """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), code_int))

            if product_id:
                conn.execute("""
                    UPDATE products
                    SET sold = sold + ?,
                        remaining = remaining - ?,
                        projected_margin = unit_price * (margin / 100.0) * GREATEST(remaining - ?, 0)
                    WHERE product_id = ?
                """, (qty, qty, qty, product_id))

            line_total_override_raw = item.get('line_total_override')
            line_total_override = (
                round2(float(line_total_override_raw))
                if line_total_override_raw not in (None, '')
                else None
            )

            processed_items.append({
                "item": item, "qty": qty, "buy_price": buy_price, "margin": margin,
                "buy_total": buy_total, "raw_line_total": raw_line_total,
                "product_id": product_id, "resolved_codes": resolved_codes,
                "line_total_override": line_total_override,
            })

        subtotal_raw = round2(sum(p["raw_line_total"] for p in processed_items))

        final_total_override = header_data.get('final_total')
        if final_total_override not in (None, '', 0):
            discounted_grand_total = round2(float(final_total_override))
        elif subtotal_raw > 0:
            discount_amount_total = round2(subtotal_raw * discount_precise / 100)
            discounted_grand_total = round2(subtotal_raw - discount_amount_total)
        else:
            discounted_grand_total = 0.0

        overrides_total = round2(sum(
            p["line_total_override"] for p in processed_items if p["line_total_override"] is not None
        ))
        remaining_target = max(0.0, round2(discounted_grand_total - overrides_total))
        remaining_subtotal_raw = round2(sum(
            p["raw_line_total"] for p in processed_items if p["line_total_override"] is None
        ))
        remaining_indices = [i for i, p in enumerate(processed_items) if p["line_total_override"] is None]
        last_remaining_idx = remaining_indices[-1] if remaining_indices else None

        running_total = 0.0
        for idx, p in enumerate(processed_items):
            item = p["item"]
            qty = p["qty"]
            if p["line_total_override"] is not None:
                sell_total = p["line_total_override"]
            elif remaining_subtotal_raw > 0:
                if idx == last_remaining_idx:
                    sell_total = round2(remaining_target - running_total)
                else:
                    sell_total = round2(p["raw_line_total"] * remaining_target / remaining_subtotal_raw)
                running_total = round2(running_total + sell_total)
            else:
                sell_total = 0.0
            sell_price = round2(sell_total / qty) if qty else 0.0
            profit = sell_total - p["buy_total"]

            item_status = 1 if is_credit else 0
            is_old_val = 1 if p.get("is_old_data") else 0
            cur_si = conn.execute("""
                INSERT INTO sold_items
                (sale_id, product_id, item_name, size, quantity,
                 unit_buy_price, margin, unit_sale_price,
                 total_buy_price, total_sale_price, status, is_return, return_qty, is_old, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
            """, (
                sale_id, p["product_id"],
                item.get('item', ''), item.get('size', '') or None, qty,
                p["buy_price"], p["margin"], sell_price,
                p["buy_total"], sell_total, item_status,
                is_old_val,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ))
            sold_item_id = cur_si.lastrowid

            for code_int in p["resolved_codes"]:
                conn.execute("""
                    INSERT INTO sold_item_barcodes (sold_item_id, barcode_no)
                    VALUES (?, ?)
                """, (sold_item_id, code_int))

            total_sell += sell_total
            total_buy += p["buy_total"]
            total_profit += profit

        advance_amount = float(header_data.get('advance_amount', 0) or 0)
        advance_amount = max(0.0, min(advance_amount, total_sell))
        if is_credit:
            if total_sell - advance_amount <= 0.01:
                bill_status = 'Paid'
            elif advance_amount > 0:
                bill_status = 'Partial'
            else:
                bill_status = 'Credit'

        conn.execute("""
            UPDATE sales
            SET total_buy_price = ?, total_sale_price = ?, total_profit = ?, status = ?,
                gross_before_discount = ?
            WHERE sale_id = ?
        """, (total_buy, total_sell, total_profit, bill_status, subtotal_raw, sale_id))

        payment_mode = header_data.get('payment_mode', 'Cash') if not is_credit else 'Credit'
        cash_amt = float(header_data.get('cash_amount', 0) or 0)
        online_amt = float(header_data.get('online_amount', 0) or 0)
        if not is_credit and cash_amt == 0 and online_amt == 0:
            cash_amt = total_sell

        paid_amount = advance_amount if is_credit else (cash_amt + online_amt)
        remaining_amount = max(0.0, total_sell - paid_amount)

        conn.execute("""
            INSERT INTO sales_payments
            (sale_id, bill_no, mode_of_payment, cash, online, discount,
             total_amount, paid_amount, remaining_amount, final_amount_discount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sale_id, header_data.get('bill_no', '') or None, payment_mode,
            cash_amt, online_amt, discount, total_sell, paid_amount, remaining_amount, total_sell
        ))

        try:
            sales_ledger = conn.execute("SELECT id FROM ledgers WHERE name = 'Sales'").fetchone()
            entries = []

            # Gross sale amount (before discount) — Tally standard double-entry:
            #   Cash / Party Dr   →  net received (total_sell)
            #   Discount Allowed Dr →  discount amount (if any)
            #   Sales            Cr  →  gross amount (subtotal_raw)
            gross_sale = round2(subtotal_raw)          # gross before discount
            discount_amount = round2(gross_sale - total_sell)  # actual discount given

            if is_credit:
                party_ledger_id = get_or_create_ledger(
                    customer_name or "Walk-in Customer", "Sundry Debtors", "Debit", conn
                )
                entries.append({"ledger_id": party_ledger_id, "debit": total_sell, "credit": 0})
            else:
                cash_ledger = conn.execute("SELECT id FROM ledgers WHERE name = 'Cash'").fetchone()
                if cash_ledger:
                    entries.append({"ledger_id": cash_ledger["id"], "debit": total_sell, "credit": 0})

            # Discount Allowed Dr — applied for both cash and credit sales if discount was given
            if discount_amount > 0.001:
                discount_ledger_id = get_or_create_ledger(
                    "Discount Allowed", "Indirect Expenses", "Debit", conn
                )
                entries.append({"ledger_id": discount_ledger_id, "debit": discount_amount, "credit": 0})

            if sales_ledger:
                entries.append({"ledger_id": sales_ledger["id"], "debit": 0, "credit": gross_sale})

            # ── Old Stock-in-Hand COGS entry (Bug B fix) ─────────────────────────
            # For every old_data line in this sale, post a cost-transfer entry in
            # the SAME voucher so that P&L shows the purchase cost:
#   Debit  Purchase          = qty * buy_price  (COGS expense)
#   Credit Old Stock-in-Hand = qty * buy_price  (reduce asset)
            old_data_buy_total = round2(sum(
                p["buy_total"] for p in processed_items if p.get("is_old_data")
            ))
            if old_data_buy_total > 0:
                purchase_ledger = conn.execute(
                    "SELECT id FROM ledgers WHERE LOWER(name) = 'purchase'"
                ).fetchone()
                if not purchase_ledger:
                    purchase_ledger_id = get_or_create_ledger(
                        "Purchase", "Purchase Accounts", "Debit", conn
                    )
                else:
                    purchase_ledger_id = purchase_ledger["id"]
                old_stock_ledger_id = get_or_create_ledger(
                    "Old Stock-in-Hand", "Current Assets", "Debit", conn
                )
                entries.append({"ledger_id": purchase_ledger_id, "debit": old_data_buy_total, "credit": 0})
                entries.append({"ledger_id": old_stock_ledger_id, "debit": 0, "credit": old_data_buy_total})
            # ─────────────────────────────────────────────────────────────────────

            if len(entries) > 1:
                result = VoucherEngine.create_voucher({
                    "voucher_type": "SALES",
                    "date": date_str,
                    "reference": header_data.get('bill_no', ''),
                    "narration": f"Sale to {customer_name or 'Walk-in Customer'}",
                    "created_by": "admin",
                    "entries": entries
                }, conn=conn)
                conn.execute(
                    "UPDATE sales SET voucher_id = ? WHERE sale_id = ?",
                    (result["voucher_id"], sale_id)
                )

            if is_credit and advance_amount > 0:
                cash_ledger = conn.execute("SELECT id FROM ledgers WHERE name = 'Cash'").fetchone()
                party_ledger_id = get_or_create_ledger(
                    customer_name or "Walk-in Customer", "Sundry Debtors", "Debit", conn
                )
                if cash_ledger:
                    VoucherEngine.create_voucher({
                        "voucher_type": "RECEIPT",
                        "date": date_str,
                        "reference": header_data.get('bill_no', ''),
                        "narration": f"Advance received from {customer_name or 'Walk-in Customer'}",
                        "created_by": "admin",
                        "entries": [
                            {"ledger_id": cash_ledger["id"], "debit": advance_amount, "credit": 0},
                            {"ledger_id": party_ledger_id, "debit": 0, "credit": advance_amount},
                        ]
                    }, conn=conn)
        except Exception as e:
            print(f"Sales voucher auto-sync warning: {e}")

        import core.dashboard_cache as dashboard_cache
        dashboard_cache.apply_transaction_delta(
            conn, date_str,
            sales_delta=total_sell,
            profit_delta=total_profit,
            cash_sales_delta=0 if is_credit else total_sell,
            credit_sales_delta=total_sell if is_credit else 0,
            txn_type="sale",
            payment_mode=payment_mode,
            recent_entry={
                "date": date_str,
                "customerName": customer_name,
                "billNo": header_data.get('bill_no', '') or '',
                "sellTotal": total_sell,
                "paymentMode": payment_mode,
            }
        )

        import core.reports_cache as reports_cache
        reports_cache.apply_sale_delta(
            conn, bill_status,
            count_delta=len(processed_items),
            qty_delta=sum(p["qty"] for p in processed_items),
            cost_delta=total_buy,
            sell_delta=total_sell,
            profit_delta=total_profit,
            bill_date=date_str,
        )

        dashboard_cache.refresh_financial_totals(conn)
        conn.commit()
        return sale_id


def update_sale_bill(sale_id, header_data, items):
    """In-place update of header fields, customer info, item line prices, and Tally vouchers."""
    with get_conn() as conn:
        sale = conn.execute("SELECT * FROM sales WHERE sale_id = ?", (sale_id,)).fetchone()
        if not sale:
            raise ValueError("Sale not found")

        date_str = header_data.get('date', sale['date'])
        if " " in str(date_str):
            date_str = str(date_str).split(" ")[0]
        header_discount = float(header_data.get('discount', sale['discount'] or 0) or 0)
        bill_no = header_data.get('bill_no', sale['bill_no'])
        customer_name = (header_data.get('customer_name') or header_data.get('customerName') or '').strip()
        customer_no = (header_data.get('customer_no') or header_data.get('customerNo') or '').strip()

        # Update customer in-place if linked
        if sale.get('customers_id') and customer_name:
            conn.execute("""
                UPDATE customers SET customer_name=?, customer_no=? WHERE customer_id=?
            """, (customer_name, customer_no, sale['customers_id']))

        conn.execute("""
            UPDATE sales SET date=?, discount=?, bill_no=? WHERE sale_id=?
        """, (date_str, header_discount, bill_no, sale_id))

        total_sell = 0.0
        gross_sell = 0.0
        total_buy = 0.0
        total_profit = 0.0
        is_credit = sale['status'] in ('Credit', 'Partial', 'Paid') and sale['status'] != 'Cash'

        for item in items:
            sold_item_id = item.get('id') or item.get('sold_item_id')
            if not sold_item_id:
                continue

            existing_si = conn.execute("""
                SELECT * FROM sold_items WHERE sold_item_id=? AND sale_id=?
            """, (sold_item_id, sale_id)).fetchone()
            if not existing_si:
                continue

            qty = float(item.get('qty', existing_si['quantity'] or 1))
            buy_price = float(item.get('buy_price', existing_si['unit_buy_price'] or 0))
            margin = float(item.get('margin', existing_si['margin'] or 0))
            actual_sell = float(item.get('sell_price', existing_si['unit_sale_price'] or 0) or 0)
            item_discount = float(item.get('discount', 0) or 0)

            unit_sell = actual_sell if actual_sell > 0 else round2(buy_price * (1 + margin / 100))
            # Apply discounts additively (item + header = combined %), matching create_sale_bill
            combined_discount_pct = item_discount + header_discount
            effective_unit_sell = round2(unit_sell * (1 - combined_discount_pct / 100))

            buy_total = qty * buy_price
            sell_total = qty * effective_unit_sell
            gross_total = qty * unit_sell
            profit = sell_total - buy_total

            conn.execute("""
                UPDATE sold_items
                SET item_name=?, size=?, quantity=?, unit_buy_price=?, margin=?,
                    unit_sale_price=?, total_buy_price=?, total_sale_price=?
                WHERE sold_item_id=? AND sale_id=?
            """, (
                item.get('item', existing_si['item_name']),
                item.get('size', existing_si['size']),
                qty, buy_price, margin, effective_unit_sell, buy_total, sell_total,
                sold_item_id, sale_id
            ))

            total_sell += sell_total
            gross_sell += gross_total
            total_buy += buy_total
            total_profit += profit

        conn.execute("""
            UPDATE sales SET total_buy_price=?, total_sale_price=?, total_profit=?,
                              gross_before_discount=? WHERE sale_id=?
        """, (total_buy, total_sell, total_profit, gross_sell, sale_id))

        existing_sp = conn.execute(
            "SELECT paid_amount FROM sales_payments WHERE sale_id=?", (sale_id,)
        ).fetchone()
        paid_amount = float(existing_sp["paid_amount"] or 0) if existing_sp else 0.0
        remaining_amount = max(0.0, total_sell - paid_amount)

        conn.execute("""
            UPDATE sales_payments
            SET bill_no=?, total_amount=?, paid_amount=?, remaining_amount=?,
                final_amount_discount=?, discount=?
            WHERE sale_id=?
        """, (bill_no, total_sell, paid_amount, remaining_amount, total_sell, header_discount, sale_id))

        # Re-sync / update Tally Voucher for Sale Edit (no duplicate entries!)
        try:
            from core.accounting import VoucherEngine
            sales_ledger = conn.execute("SELECT id FROM ledgers WHERE name = 'Sales'").fetchone()
            cash_ledger = conn.execute("SELECT id FROM ledgers WHERE name = 'Cash'").fetchone()
            discount_amount = round2(gross_sell - total_sell)
            if sales_ledger:
                entries = []
                if is_credit:
                    cust_ledger_id = get_or_create_ledger(
                        customer_name or "Unknown Customer", "Sundry Debtors", "Debit", conn
                    )
                    entries.append({"ledger_id": cust_ledger_id, "debit": total_sell, "credit": 0})
                else:
                    if cash_ledger:
                        entries.append({"ledger_id": cash_ledger["id"], "debit": total_sell, "credit": 0})

                if discount_amount > 0.001:
                    discount_ledger_id = get_or_create_ledger(
                        "Discount Allowed", "Indirect Expenses", "Debit", conn
                    )
                    entries.append({"ledger_id": discount_ledger_id, "debit": discount_amount, "credit": 0})

                entries.append({"ledger_id": sales_ledger["id"], "debit": 0, "credit": gross_sell if discount_amount > 0.001 else total_sell})

                v_id = sale.get('voucher_id')
                v_data = {
                    "voucher_type": "SALES",
                    "date": date_str,
                    "reference": bill_no,
                    "narration": f"Sale to {customer_name or 'Customer'}",
                    "entries": entries
                }
                if v_id:
                    VoucherEngine.update_voucher(v_id, v_data, conn=conn)
                else:
                    res = VoucherEngine.create_voucher(dict(v_data, created_by="admin"), conn=conn)
                    conn.execute("UPDATE sales SET voucher_id = ? WHERE sale_id = ?", (res["voucher_id"], sale_id))
        except Exception as ve:
            print(f"[Warning] Failed to update Tally voucher for sale #{sale_id}: {ve}")

        import core.dashboard_cache as dashboard_cache
        dashboard_cache.recompute_all(conn)
        import core.reports_cache as reports_cache
        reports_cache.recompute_all(conn)

        conn.commit()
        return sale_id


def get_sale_bill(sale_id):
    with get_conn() as conn:
        header = conn.execute("""
            SELECT s.*, c.customer_name, c.customer_no,
                   CASE WHEN s.status = 'Cash' THEN 'cash' ELSE 'credit' END AS mode,
                   sp.mode_of_payment AS payment_mode, sp.cash, sp.online
            FROM sales s
            LEFT JOIN customers c ON c.customer_id = s.customers_id
            LEFT JOIN sales_payments sp ON sp.sale_id = s.sale_id
            WHERE s.sale_id = ?
        """, (sale_id,)).fetchone()
        if not header:
            return None
        items = conn.execute("""
            SELECT sold_item_id AS id, product_id, item_name AS item, size, quantity AS qty,
                   unit_buy_price AS buy_price, margin, unit_sale_price AS sell_price,
                   total_buy_price AS buy_total, total_sale_price AS sell_total, status
            FROM sold_items WHERE sale_id = ?
        """, (sale_id,)).fetchall()
        return dict(header), [dict(it) for it in items]


def get_sale_rows(filters=None, limit=None, offset=None):
    with get_conn() as conn:
        # Bill-level WHERE -- filters that only touch the sales header row.
        # When paginating (limit set) these are applied to a cheap indexed
        # scan over `sales` alone; the sold_items join (4.8M+ rows on a
        # busy shop) is then done only for the page's bills.
        bill_where = "WHERE 1=1"
        bill_params = []
        has_customer_filter = False
        if filters:
            if 'mode' in filters:
                mode = filters['mode']
                if mode == 'cash':
                    bill_where += " AND s.status = 'Cash'"
                elif mode == 'credit':
                    bill_where += " AND s.status IN ('Credit','Partial','Paid')"
            if 'date_from' in filters:
                bill_where += " AND s.date >= ?"
                bill_params.append(filters['date_from'])
            if 'date_to' in filters:
                bill_where += " AND s.date <= ?"
                bill_params.append(filters['date_to'])
            if filters.get('customer'):
                has_customer_filter = True
                bill_where += " AND c.customer_name LIKE ?"
                bill_params.append(f"%{filters['customer']}%")

        if limit is not None:
            # Resolve the page of bill ids first (index scan on idx_sales_date,
            # ~10ms), then fetch only those bills' items. A single query that
            # joins+orders sold_items and then LIMITs had to sort the entire
            # joined table (2.4M+ rows for 'cash') before slicing the page.
            cust_join = "LEFT JOIN customers c ON c.customer_id = s.customers_id" if has_customer_filter else ""
            ids = None
            if offset and int(offset) >= 1000 and not has_customer_filter and 'date_from' not in (filters or {}) and 'date_to' not in (filters or {}):
                max_sale_row = conn.execute("SELECT MAX(sale_id) as m FROM sales").fetchone()
                max_sale_id = max_sale_row['m'] if max_sale_row else 0
                if max_sale_id:
                    mode_val = (filters or {}).get('mode')
                    multiplier = 2.0 if mode_val in ('cash', 'credit') else 1.0
                    target_sale_id = max_sale_id - int(int(offset) * multiplier)
                    if target_sale_id > 0:
                        fast_cond = ""
                        if mode_val == 'cash':
                            fast_cond = " AND s.status = 'Cash'"
                        elif mode_val == 'credit':
                            fast_cond = " AND s.status IN ('Credit','Partial','Paid')"
                        fast_ids = conn.execute(f"""
                            SELECT s.sale_id
                            FROM sales s
                            WHERE s.sale_id <= ? {fast_cond}
                            ORDER BY s.sale_id DESC
                            LIMIT ?
                        """, [target_sale_id, int(limit)]).fetchall()
                        if fast_ids and len(fast_ids) >= int(limit):
                            ids = fast_ids

            if ids is None:
                ids = conn.execute(f"""
                    SELECT s.sale_id
                    FROM sales s
                    {cust_join}
                    {bill_where}
                    ORDER BY s.date DESC, s.sale_id DESC
                    LIMIT ? OFFSET ?
                """, bill_params + [int(limit), int(offset or 0)]).fetchall()
            if not ids:
                return []
            sale_ids = [r["sale_id"] for r in ids]
            query = """
                SELECT
                    s.sale_id,
                    s.bill_no,
                    c.customer_name,
                    c.customer_no,
                    s.date,
                    CASE WHEN s.status = 'Cash' THEN 'cash' ELSE 'credit' END AS mode,
                    s.status,
                    COALESCE(sp.mode_of_payment, s.status) AS payment_mode,
                    si.sold_item_id AS item_id,
                    si.item_name AS item,
                    si.size,
                    si.quantity AS qty,
                    si.unit_buy_price AS buy_price,
                    si.margin,
                    si.unit_sale_price AS sell_price,
                    si.unit_sale_price AS "sellUnit",
                    si.total_buy_price AS buy_total,
                    si.total_buy_price AS "buyTotal",
                    si.total_sale_price AS sell_total,
                    si.total_sale_price AS "sellTotal",
                    (si.total_sale_price - si.total_buy_price) AS profit,
                    s.discount,
                    s.gross_before_discount AS "subTotal",
                    COALESCE(sp.cash, 0) AS "cashAmount",
                    COALESCE(sp.online, 0) AS "onlineAmount",
                    COALESCE(sp.paid_amount, 0) AS "paidAmount",
                    COALESCE(sp.remaining_amount, 0) AS "remainingAmount"
                FROM sales s
                JOIN sold_items si ON si.sale_id = s.sale_id
                LEFT JOIN customers c ON c.customer_id = s.customers_id
                LEFT JOIN sales_payments sp ON sp.sale_id = s.sale_id
                WHERE si.is_return IS DISTINCT FROM 1
                  AND s.sale_id = ANY(?)
                ORDER BY s.date DESC, s.sale_id DESC, si.sold_item_id
            """
            return [dict(r) for r in conn.execute(query, [sale_ids]).fetchall()]

        # Non-paginated path (no limit) -- join everything as before.
        query = """
            SELECT
                s.sale_id,
                s.bill_no,
                c.customer_name,
                c.customer_no,
                s.date,
                CASE WHEN s.status = 'Cash' THEN 'cash' ELSE 'credit' END AS mode,
                s.status,
                COALESCE(sp.mode_of_payment, s.status) AS payment_mode,
                si.sold_item_id AS item_id,
                si.item_name AS item,
                si.size,
                si.quantity AS qty,
                si.unit_buy_price AS buy_price,
                si.margin,
                si.unit_sale_price AS sell_price,
                si.unit_sale_price AS "sellUnit",
                si.total_buy_price AS buy_total,
                si.total_buy_price AS "buyTotal",
                si.total_sale_price AS sell_total,
                si.total_sale_price AS "sellTotal",
                (si.total_sale_price - si.total_buy_price) AS profit,
                s.discount,
                s.gross_before_discount AS "subTotal",
                COALESCE(sp.cash, 0) AS "cashAmount",
                COALESCE(sp.online, 0) AS "onlineAmount",
                COALESCE(sp.paid_amount, 0) AS "paidAmount",
                COALESCE(sp.remaining_amount, 0) AS "remainingAmount"
            FROM sales s
            JOIN sold_items si ON si.sale_id = s.sale_id
            LEFT JOIN customers c ON c.customer_id = s.customers_id
            LEFT JOIN sales_payments sp ON sp.sale_id = s.sale_id
            WHERE si.is_return IS DISTINCT FROM 1
        """
        params = []
        if filters:
            if 'mode' in filters:
                mode = filters['mode']
                if mode == 'cash':
                    query += " AND s.status = 'Cash'"
                elif mode == 'credit':
                    query += " AND s.status IN ('Credit','Partial','Paid')"
            if 'date_from' in filters:
                query += " AND s.date >= ?"
                params.append(filters['date_from'])
            if 'date_to' in filters:
                query += " AND s.date <= ?"
                params.append(filters['date_to'])
            if 'customer' in filters and filters['customer']:
                query += " AND c.customer_name LIKE ?"
                params.append(f"%{filters['customer']}%")
        query += " ORDER BY s.date DESC, s.sale_id DESC, si.sold_item_id"
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def get_sale_stats(filters=None):
    with get_conn() as conn:
        query = """
            SELECT
                COUNT(si.sold_item_id) as total_sells,
                COALESCE(SUM(si.quantity), 0) as total_qty,
                COALESCE(SUM(si.total_buy_price), 0) as total_cost,
                COALESCE(SUM(si.total_sale_price), 0) as total_sell_amt,
                COALESCE(SUM(si.total_sale_price - si.total_buy_price), 0) as total_profit
            FROM sales s
            JOIN sold_items si ON si.sale_id = s.sale_id
            WHERE si.is_return IS DISTINCT FROM 1
        """
        params = []
        if filters:
            if 'mode' in filters:
                mode = filters['mode']
                if mode == 'cash':
                    query += " AND s.status = 'Cash'"
                elif mode == 'credit':
                    query += " AND s.status IN ('Credit','Partial','Paid')"
            if 'date_from' in filters:
                query += " AND s.date >= ?"
                params.append(filters['date_from'])
            if 'date_to' in filters:
                query += " AND s.date <= ?"
                params.append(filters['date_to'])
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else {
            "total_sells": 0, "total_qty": 0, "total_cost": 0,
            "total_sell_amt": 0, "total_profit": 0
        }


def get_sale_rows_count(filters=None):
    # Fast path: if filters is empty or only contains 'mode', read sale_count directly
    # from reports_stats_cache table (0.2ms instead of 500ms!)
    if not filters or (set(filters.keys()).issubset({'mode'}) and filters.get('mode') in (None, 'all', 'cash', 'credit')):
        mode_val = (filters or {}).get('mode') or 'all'
        with get_conn() as conn:
            row = conn.execute(
                "SELECT sale_count FROM reports_stats_cache WHERE mode = ?", (mode_val,)
            ).fetchone()
            if row and row['sale_count'] is not None and row['sale_count'] > 0:
                return int(row['sale_count'])

    with get_conn() as conn:
        has_customer = filters and filters.get('customer')
        cust_join = "LEFT JOIN customers c ON c.customer_id = s.customers_id" if has_customer else ""
        query = f"""
            SELECT COUNT(*) as c
            FROM sales s
            {cust_join}
            WHERE 1=1
        """
        params = []
        if filters:
            if 'mode' in filters:
                mode = filters['mode']
                if mode == 'cash':
                    query += " AND s.status = 'Cash'"
                elif mode == 'credit':
                    query += " AND s.status IN ('Credit','Partial','Paid')"
            if 'date_from' in filters:
                query += " AND s.date >= ?"
                params.append(filters['date_from'])
            if 'date_to' in filters:
                query += " AND s.date <= ?"
                params.append(filters['date_to'])
            if filters.get('customer'):
                query += " AND c.customer_name LIKE ?"
                params.append(f"%{filters['customer']}%")
        return conn.execute(query, params).fetchone()["c"]


@sales_bp.route("/api/sale_bill", methods=["POST"])
def api_sale_bill():
    data = request.json or {}
    header = data.get("header") or data
    items = data.get("items") or []
    mode = data.get("mode") or header.get("mode") or "cash"
    if not items:
        return jsonify({"status": "error", "message": "No items"}), 400
    try:
        sid = create_sale_bill(header, items, mode)
        return jsonify({"status": "ok", "saleId": sid, "id": sid})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 400


@sales_bp.route("/api/sale_bill/<int:sale_id>", methods=["GET"])
def api_get_sale_bill(sale_id):
    result = get_sale_bill(sale_id)
    if not result:
        return jsonify({"error": "Not found"}), 404
    header, items = result
    return jsonify({"header": header, "items": items})


@sales_bp.route("/api/sale_bill/<int:sale_id>", methods=["PUT"])
def api_update_sale_bill(sale_id):
    data = request.json or {}
    header = data.get("header") or data
    items = data.get("items") or []
    try:
        update_sale_bill(sale_id, header, items)
        return jsonify({"status": "ok", "saleId": sale_id})
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@sales_bp.route("/api/sales_returns", methods=["GET"])
def get_sales_returns():
    """Return list of saved sales return lines (from sales_return_items)."""
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
            where_sql += " AND date >= ?"
            params.append(date_from)
        if date_to:
            where_sql += " AND date <= ?"
            params.append(date_to)

        total = conn.execute(
            f"SELECT COUNT(*) c FROM sales_return_items {where_sql}", params
        ).fetchone()["c"]

        rows = conn.execute(f"""
            SELECT return_bill_no, customer_name, item_name AS item, size, qty,
                   sell_total, reason, date
            FROM sales_return_items
            {where_sql}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()

    # Keys renamed to camelCase here (returnBillNo, customerName, sellTotal)
    # to match renderSalesReturnBills() in sales/returns.js, and wrapped as
    # {entries,total,page,limit} -- the same convention that module's
    # loadSalesReturnBills() already expects.
    entries = [
        {
            "returnBillNo": r["return_bill_no"],
            "customerName": r["customer_name"],
            "item": r["item"],
            "size": r["size"],
            "qty": float(r["qty"] or 0),
            "sellTotal": float(r["sell_total"] or 0),
            "reason": r["reason"],
            "date": r["date"],
        }
        for r in rows
    ]
    return jsonify({"entries": entries, "total": total, "page": page, "limit": limit})


@sales_bp.route("/api/sale_bills/search", methods=["GET"])
def api_sale_bills_search():
    q = (request.args.get("q") or "").strip()
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT s.sale_id, s.bill_no, s.date, s.status, s.total_sale_price,
                   c.customer_name, c.customer_no
            FROM sales s
            LEFT JOIN customers c ON c.customer_id = s.customers_id
            WHERE s.bill_no ILIKE ? OR c.customer_name ILIKE ?
            ORDER BY s.date DESC LIMIT 50
        """, (f"%{q}%", f"%{q}%")).fetchall()
    # Keys renamed/added here to match sales/returns.js, which groups
    # results by r.sourceTable + r.billNo and reads r.customerName --
    # none of which the raw row (sale_id / bill_no / customer_name,
    # no sourceTable) provided.
    return jsonify([
        {
            "sourceTable": "sales",
            "sale_id": r["sale_id"],
            "billNo": r["bill_no"],
            "date": r["date"],
            "status": r["status"],
            "customerName": r["customer_name"],
            "customerNo": r["customer_no"],
            "total_sale_price": r["total_sale_price"],
        }
        for r in rows
    ])


@sales_bp.route("/api/sale_bills/<table>/<bill_no>", methods=["GET"])
def api_sale_bill_items(table, bill_no):
    with get_conn() as conn:
        sale = conn.execute(
            "SELECT sale_id FROM sales WHERE bill_no = ?", (bill_no,)
        ).fetchone()
        if not sale:
            return jsonify([])
        items = conn.execute("""
            SELECT sold_item_id AS id, product_id, item_name AS item, size,
                   GREATEST(quantity - COALESCE(return_qty, 0), 0) AS qty,
                   quantity AS original_qty,
                   COALESCE(return_qty, 0) AS return_qty,
                   unit_sale_price AS sell_price, unit_sale_price AS "sellUnit",
                   total_sale_price AS sell_total,
                   COALESCE(is_old, 0) AS is_old
            FROM sold_items
            WHERE sale_id = ? AND (quantity - COALESCE(return_qty, 0)) > 0
        """, (sale["sale_id"],)).fetchall()
    return jsonify([dict(r) for r in items])


@sales_bp.route("/api/sales_return_bill", methods=["POST"])
def api_sales_return_bill():
    data = request.json or {}
    items = data.get("items") or []
    reason = data.get("reason") or ""
    if not items:
        return jsonify({"status": "error", "message": "No items"}), 400

    with get_conn() as conn:
        today = datetime.now().strftime("%Y%m%d")
        cnt = conn.execute(
            "SELECT COUNT(DISTINCT return_bill_no) c FROM sales_return_items WHERE return_bill_no LIKE ?",
            (f"SR{today}%",)
        ).fetchone()["c"]
        return_bill_no = f"SR{today}-{str(cnt+1).zfill(4)}"
        total_return_net = 0.0
        total_return_discount = 0.0
        total_old_data_return_buy = 0.0
        customer_credits = {}
        try:
            for it in items:
                # Barcode-driven line (scan/enter mode, mirrors purchase
                # returns): each line is exactly one physical unit, and the
                # sold_item it belongs to is resolved from the barcode
                # itself rather than being picked by the caller.
                barcode_val = it.get("barcode")
                sold_item_id = it.get("id") or it.get("sold_item_id") or it.get("originalId")
                ret_qty = float(it.get("qty") or it.get("return_qty") or 1.0)
                barcode_int = None
                if barcode_val is not None:
                    try:
                        barcode_int = int(barcode_val)
                    except (TypeError, ValueError):
                        pass

                si = None
                od_rec = None
                is_direct_old_data = False

                if barcode_val is not None:
                    ret_qty = 1.0
                    sib = None
                    if barcode_int is not None:
                        sib = conn.execute(
                            "SELECT sold_item_id FROM sold_item_barcodes WHERE barcode_no = ?",
                            (barcode_int,)
                        ).fetchone()
                    if sib:
                        sold_item_id = sib["sold_item_id"]
                        pi = conn.execute(
                            "SELECT is_available FROM purchase_item WHERE barcode_no = ?", (barcode_int,)
                        ).fetchone()
                        if not pi or pi["is_available"] != "sold":
                            raise ValueError(f"Barcode {barcode_int} has already been returned or is not currently sold")
                    else:
                        # Check if barcode_val is an old_data item that was recorded in sold_items
                        si_old = None
                        if barcode_int is not None:
                            si_old = conn.execute("""
                                SELECT *
                                FROM sold_items
                                WHERE is_old = 1 AND (product_id = ? OR sold_item_id = ?) AND return_qty < quantity
                                ORDER BY sold_item_id DESC LIMIT 1
                            """, (barcode_int, barcode_int)).fetchone()
                        if not si_old and barcode_val:
                            si_old = conn.execute("""
                                SELECT *
                                FROM sold_items
                                WHERE is_old = 1 AND LOWER(TRIM(item_name)) = LOWER(TRIM(?)) AND return_qty < quantity
                                ORDER BY sold_item_id DESC LIMIT 1
                            """, (str(barcode_val),)).fetchone()

                        if si_old:
                            sold_item_id = si_old["sold_item_id"]
                            si = si_old
                        else:
                            # Not in sold_items: check directly in old_data table!
                            if barcode_int is not None:
                                od_rec = conn.execute(
                                    "SELECT * FROM old_data WHERE uniqee_id = ? OR id = ?",
                                    (barcode_int, barcode_int)
                                ).fetchone()
                            if not od_rec and barcode_val:
                                od_rec = conn.execute(
                                    "SELECT * FROM old_data WHERE LOWER(TRIM(item_code)) = LOWER(TRIM(?)) ORDER BY id ASC LIMIT 1",
                                    (str(barcode_val),)
                                ).fetchone()
                            if od_rec:
                                is_direct_old_data = True
                            else:
                                raise ValueError(f"Barcode / ID {barcode_val} not found in stock or sales")
                else:
                    if sold_item_id:
                        try:
                            s_id_int = int(sold_item_id)
                        except (TypeError, ValueError):
                            s_id_int = None
                        if s_id_int is not None:
                            si = conn.execute(
                                "SELECT * FROM sold_items WHERE sold_item_id = ?", (s_id_int,)
                            ).fetchone()
                        if not si:
                            # Check directly in old_data table
                            if s_id_int is not None:
                                od_rec = conn.execute(
                                    "SELECT * FROM old_data WHERE uniqee_id = ? OR id = ?",
                                    (s_id_int, s_id_int)
                                ).fetchone()
                            if not od_rec and sold_item_id:
                                od_rec = conn.execute(
                                    "SELECT * FROM old_data WHERE LOWER(TRIM(item_code)) = LOWER(TRIM(?)) ORDER BY id ASC LIMIT 1",
                                    (str(sold_item_id),)
                                ).fetchone()
                            if od_rec:
                                is_direct_old_data = True
                            else:
                                raise ValueError(f"sold_item {sold_item_id} not found")
                    else:
                        raise ValueError("sold_item id or barcode required")

                if is_direct_old_data:
                    # Direct return of old_data item (no prior sold_items record required)
                    old_uid = od_rec["uniqee_id"] or od_rec["id"]
                    conn.execute("""
                        UPDATE old_data
                        SET remaining = remaining + ?,
                            sold = GREATEST(sold - ?, 0),
                            is_return = 1
                        WHERE uniqee_id = ? OR id = ?
                    """, (ret_qty, ret_qty, old_uid, old_uid))

                    line_return_value = round2(ret_qty * float(od_rec["sell_mrp"] or 0))
                    line_buy_value = round2(ret_qty * float(od_rec["buy_mrp"] or 0))
                    total_return_net += line_return_value
                    total_old_data_return_buy += line_buy_value

                    conn.execute("""
                        INSERT INTO sales_return_items
                            (return_bill_no, sold_item_id, customer_name, customer_no,
                             item_name, size, qty, sell_price, sell_total, reason, date)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        return_bill_no, None,
                        "Walk-in Customer", None,
                        od_rec["item_code"], od_rec.get("size") or "", ret_qty,
                        float(od_rec["sell_mrp"] or 0), line_return_value, reason,
                        datetime.now().strftime("%Y-%m-%d"),
                    ))

                    line_profit_delta = -(line_return_value - line_buy_value)
                    sale_date = datetime.now().strftime("%Y-%m-%d")
                    cust_key = ("Walk-in Customer", False)
                    customer_credits[cust_key] = customer_credits.get(cust_key, 0.0) + line_return_value

                    import core.dashboard_cache as dashboard_cache
                    dashboard_cache.apply_transaction_delta(
                        conn, sale_date,
                        sales_delta=-line_return_value,
                        profit_delta=line_profit_delta,
                        cash_sales_delta=-line_return_value,
                        credit_sales_delta=0,
                    )
                    continue

                if not si:
                    si = conn.execute(
                        "SELECT * FROM sold_items WHERE sold_item_id = ?", (sold_item_id,)
                    ).fetchone()
                if not si:
                    raise ValueError(f"sold_item {sold_item_id} not found")
                already = float(si["return_qty"] or 0)
                if already + ret_qty > float(si["quantity"]):
                    raise ValueError("Return qty exceeds sold qty")

                is_old_line = (int(si["is_old"] or 0) == 1) if "is_old" in si.keys() else False

                if is_old_line:
                    # Restore stock in old_data table using product_id (which stores uniqee_id or id)
                    old_uid = si["product_id"]
                    if old_uid is not None:
                        conn.execute("""
                            UPDATE old_data
                            SET remaining = remaining + ?,
                                sold = GREATEST(sold - ?, 0),
                                is_return = 1
                            WHERE uniqee_id = ? OR id = ?
                        """, (ret_qty, ret_qty, old_uid, old_uid))
                else:
                    if barcode_no:
                        # This exact scanned unit, not an arbitrary batch pick.
                        barcodes = [{"barcode_no": barcode_no}]
                    else:
                        barcodes = conn.execute("""
                            SELECT barcode_no FROM sold_item_barcodes
                            WHERE sold_item_id = ? ORDER BY id LIMIT ?
                        """, (sold_item_id, int(ret_qty))).fetchall()
                    for bc in barcodes:
                        conn.execute("""
                            UPDATE purchase_item SET is_available='available', sold_at=NULL
                            WHERE barcode_no=?
                        """, (bc["barcode_no"],))
                        if si["product_id"]:
                            conn.execute("""
                                UPDATE products SET
                                    sold = GREATEST(sold-1,0),
                                    remaining = remaining + 1,
                                    projected_margin = unit_price * (margin/100.0) * (remaining + 1)
                                WHERE product_id=?
                            """, (si["product_id"],))

                new_ret = already + ret_qty
                is_ret = 1 if new_ret >= float(si["quantity"]) else 0
                conn.execute("""
                    UPDATE sold_items SET return_qty=?, is_return=? WHERE sold_item_id=?
                """, (new_ret, is_ret, sold_item_id))
                line_return_value = round2(ret_qty * float(si["unit_sale_price"] or 0))
                line_buy_value = round2(ret_qty * float(si["unit_buy_price"] or 0))
                total_return_net += line_return_value
                if is_old_line:
                    total_old_data_return_buy += line_buy_value

                # Update return_qty and is_return flag based on the ORIGINAL quantity (do not
                # also reduce quantity — that causes the is_return threshold to shrink each return)
                conn.execute("""
                    UPDATE sold_items SET
                        total_sale_price  = GREATEST(total_sale_price - ?, 0),
                        total_buy_price   = GREATEST(total_buy_price  - ?, 0)
                    WHERE sold_item_id = ?
                """, (line_return_value, line_buy_value, sold_item_id))

                # Persist this return line so it can actually be listed
                # later (previously nothing about the return -- bill no,
                # reason, qty, value -- was ever saved anywhere).
                sale_hdr = conn.execute("""
                    SELECT c.customer_name, c.customer_no, s.customers_id, s.date, s.status, s.bill_no,
                           s.total_sale_price, s.total_buy_price, s.total_profit, s.discount, s.voucher_id
                    FROM sales s
                    LEFT JOIN customers c ON c.customer_id = s.customers_id
                    WHERE s.sale_id = ?
                """, (si["sale_id"],)).fetchone()
                conn.execute("""
                    INSERT INTO sales_return_items
                        (return_bill_no, sold_item_id, customer_name, customer_no,
                         item_name, size, qty, sell_price, sell_total, reason, date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    return_bill_no, sold_item_id,
                    sale_hdr["customer_name"] if sale_hdr else None,
                    sale_hdr["customer_no"] if sale_hdr else None,
                    si["item_name"], si["size"], ret_qty,
                    si["unit_sale_price"], line_return_value, reason,
                    datetime.now().strftime("%Y-%m-%d"),
                ))

                # Calculate proportional return discount for this line
                line_return_discount = 0.0
                if sale_hdr and sale_hdr["voucher_id"]:
                    disc_ledger_check = conn.execute("SELECT id FROM ledgers WHERE name = 'Discount Allowed'").fetchone()
                    if disc_ledger_check:
                        disc_entry = conn.execute("""
                            SELECT debit FROM voucher_entries 
                            WHERE voucher_id = ? AND ledger_id = ?
                        """, (sale_hdr["voucher_id"], disc_ledger_check["id"])).fetchone()
                        if disc_entry and float(disc_entry["debit"] or 0) > 0.001:
                            orig_disc = float(disc_entry["debit"])
                            v_cash_party = conn.execute("""
                                SELECT ve.debit FROM voucher_entries ve
                                JOIN ledgers l ON l.id = ve.ledger_id
                                WHERE ve.voucher_id = ? AND l.name NOT IN ('Discount Allowed', 'Purchase') AND ve.debit > 0
                                ORDER BY ve.id ASC
                            """, (sale_hdr["voucher_id"],)).fetchone()
                            orig_net = float(v_cash_party["debit"]) if v_cash_party else float(sale_hdr["total_sale_price"] or 0)
                            if orig_net > 0:
                                disc_ratio = orig_disc / orig_net
                                line_return_discount = round2(line_return_value * disc_ratio)

                if line_return_discount <= 0.001:
                    buy_p = float(si["unit_buy_price"] or 0)
                    margin_p = float(si["margin"] or 0)
                    if buy_p > 0 and margin_p > 0:
                        calc_gross_unit = round2(buy_p * (1.0 + margin_p / 100.0))
                        if calc_gross_unit > float(si["unit_sale_price"] or 0) + 0.001:
                            line_return_gross_temp = round2(ret_qty * calc_gross_unit)
                            line_return_discount = round2(line_return_gross_temp - line_return_value)

                if line_return_discount <= 0.001 and sale_hdr and float(sale_hdr["discount"] or 0) > 0:
                    disc_pct = float(sale_hdr["discount"])
                    if 0 < disc_pct < 100:
                        gross_unit = float(si["unit_sale_price"] or 0) / (1.0 - disc_pct / 100.0)
                        line_return_gross_temp = round2(ret_qty * gross_unit)
                        line_return_discount = round2(line_return_gross_temp - line_return_value)

                total_return_discount += line_return_discount

                # Mirror what purchase returns already do: pull today's/this
                # week's/this month's cached dashboard totals down by the
                # returned amount, instead of leaving them at the original
                # (pre-return) sale value until the next full recompute.
                line_profit_delta = -(line_return_value - line_buy_value)
                sale_date = sale_hdr["date"] if sale_hdr else datetime.now().strftime("%Y-%m-%d")
                sale_status = (sale_hdr["status"] if sale_hdr else "Cash") or "Cash"
                is_credit_sale = sale_status in ("Credit", "Partial")

                if sale_hdr:
                    new_sale_total = max(0.0, float(sale_hdr["total_sale_price"] or 0) - line_return_value)
                    new_buy_total = max(0.0, float(sale_hdr["total_buy_price"] or 0) - line_buy_value)
                    new_profit_total = float(sale_hdr["total_profit"] or 0) + line_profit_delta
                    new_status = 'Paid' if (is_credit_sale and new_sale_total <= 0.01) else sale_status
                    conn.execute("""
                        UPDATE sales SET
                            total_sale_price = ?,
                            total_buy_price = ?,
                            total_profit = ?,
                            status = ?
                        WHERE sale_id = ?
                    """, (new_sale_total, new_buy_total, new_profit_total, new_status, si["sale_id"]))

                    # FIX 2: Keep sales_payments in sync with the return so that
                    # paid_amount / remaining_amount on the bill also reflect the return.
                    sp = conn.execute(
                        "SELECT * FROM sales_payments WHERE sale_id = ?", (si["sale_id"],)
                    ).fetchone()
                    if sp:
                        sp_mode = (sp["mode_of_payment"] or "").lower()
                        sp_cash   = float(sp["cash"]   or 0)
                        sp_online = float(sp["online"] or 0)
                        sp_paid   = float(sp["paid_amount"]   or 0)
                        sp_total  = float(sp["total_amount"]  or 0)

                        new_sp_total  = max(0.0, round2(sp_total  - line_return_value))
                        new_sp_paid   = max(0.0, round2(sp_paid   - line_return_value))
                        new_sp_remain = max(0.0, round2(new_sp_total - new_sp_paid))

                        # Subtract the refund from whichever payment column was used
                        if sp_online > 0 and sp_mode in ("online", "upi", "card"):
                            new_sp_online = max(0.0, round2(sp_online - line_return_value))
                            new_sp_cash   = sp_cash
                        else:
                            new_sp_cash   = max(0.0, round2(sp_cash   - line_return_value))
                            new_sp_online = sp_online

                        conn.execute("""
                            UPDATE sales_payments SET
                                total_amount     = ?,
                                paid_amount      = ?,
                                remaining_amount = ?,
                                cash             = ?,
                                online           = ?
                            WHERE sale_id = ?
                        """, (new_sp_total, new_sp_paid, new_sp_remain,
                               new_sp_cash, new_sp_online, si["sale_id"]))

                    if is_credit_sale and new_status == 'Paid' and sale_hdr.get("customers_id"):
                        open_sales = conn.execute("""
                            SELECT COUNT(*) c FROM sales
                            WHERE customers_id = ? AND status IN ('Credit','Partial') AND sale_id != ?
                        """, (sale_hdr["customers_id"], si["sale_id"])).fetchone()["c"]
                        if open_sales == 0:
                            conn.execute(
                                "UPDATE customers SET status = 0 WHERE customer_id = ?",
                                (sale_hdr["customers_id"],)
                            )

                cust_key = (sale_hdr["customer_name"] if (sale_hdr and sale_hdr["customer_name"]) else "Walk-in Customer", is_credit_sale)
                customer_credits[cust_key] = customer_credits.get(cust_key, 0.0) + line_return_value

                import core.dashboard_cache as dashboard_cache
                dashboard_cache.apply_transaction_delta(
                    conn, sale_date,
                    sales_delta=-line_return_value,
                    profit_delta=line_profit_delta,
                    cash_sales_delta=0 if is_credit_sale else -line_return_value,
                    credit_sales_delta=-line_return_value if is_credit_sale else 0,
                )
                dashboard_cache.adjust_recent_sale_amount(
                    conn, sale_date,
                    sale_hdr["bill_no"] if sale_hdr else None, -line_return_value
                )

            try:
                total_return_gross = round2(total_return_net + total_return_discount)
                sales_l = conn.execute("SELECT id FROM ledgers WHERE name='Sales'").fetchone()
                cash_l = conn.execute("SELECT id FROM ledgers WHERE name='Cash'").fetchone()
                if sales_l and total_return_net > 0:
                    entries = [
                        {"ledger_id": sales_l["id"], "debit": total_return_gross, "credit": 0},
                    ]
                    if total_return_discount > 0.001:
                        discount_ledger_id = get_or_create_ledger(
                            "Discount Allowed", "Indirect Expenses", "Debit", conn
                        )
                        entries.append({"ledger_id": discount_ledger_id, "debit": 0, "credit": total_return_discount})

                    for (c_name, is_credit), c_amount in customer_credits.items():
                        if c_amount <= 0.001:
                            continue
                        if is_credit and c_name and c_name != "Walk-in Customer":
                            party_ledger_id = get_or_create_ledger(
                                c_name, "Sundry Debtors", "Debit", conn
                            )
                            entries.append({"ledger_id": party_ledger_id, "debit": 0, "credit": c_amount})
                        else:
                            if cash_l:
                                entries.append({"ledger_id": cash_l["id"], "debit": 0, "credit": c_amount})

                    # ── Old Stock-in-Hand COGS reversal ──────────────────
                    # If any old_data items were returned, reverse the cost transfer:
                    #   Debit  Old Stock-in-Hand = buy_cost (restores asset on balance sheet)
                    #   Credit Purchase          = buy_cost (reduces COGS expense on P&L)
                    if total_old_data_return_buy > 0.001:
                        old_stock_ledger_id = get_or_create_ledger(
                            "Old Stock-in-Hand", "Current Assets", "Debit", conn
                        )
                        purchase_ledger = conn.execute(
                            "SELECT id FROM ledgers WHERE LOWER(name) = 'purchase'"
                        ).fetchone()
                        if not purchase_ledger:
                            purchase_ledger_id = get_or_create_ledger(
                                "Purchase", "Purchase Accounts", "Debit", conn
                            )
                        else:
                            purchase_ledger_id = purchase_ledger["id"]

                        entries.append({"ledger_id": old_stock_ledger_id, "debit": round2(total_old_data_return_buy), "credit": 0})
                        entries.append({"ledger_id": purchase_ledger_id, "debit": 0, "credit": round2(total_old_data_return_buy)})

                    VoucherEngine.create_voucher({
                        "voucher_type": "SALESRET",
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "reference": return_bill_no,
                        "narration": f"Sales return {reason}".strip(),
                        "created_by": "admin",
                        "entries": entries
                    }, conn=conn)
            except Exception as e:
                print(f"Sales return voucher warning: {e}")
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400
        dashboard_cache.refresh_financial_totals(conn)
        conn.commit()
    _trigger_async_cache_recompute()
    return jsonify({"status": "ok", "returnBillNo": return_bill_no})


@sales_bp.route("/api/replace_sale", methods=["POST"])
def api_replace_sale():
    """Exchange/replace — kept feature; uses purchase_item for barcode lookups."""
    data = request.json or {}
    old_items = data.get("old_items") or data.get("oldItems") or data.get("return_items") or []
    new_items = data.get("new_items") or data.get("newItems") or data.get("give_items") or []
    customer_name = data.get("customer_name") or data.get("customerName") or ""
    customer_no = data.get("customer_no") or data.get("customerNo") or ""
    note = data.get("note") or ""
    discount = float(data.get("discount", 0) or 0)
    date_str = data.get("date") or datetime.now().strftime("%Y-%m-%d")

    with get_conn() as conn:
        today = datetime.now().strftime("%Y%m%d")
        cnt = conn.execute(
            "SELECT COUNT(*) c FROM replace_bills WHERE replaceBillNo LIKE ?",
            (f"RB{today}%",)
        ).fetchone()["c"]
        replace_no = f"RB{today}-{str(cnt+1).zfill(4)}"
        old_total = 0.0
        new_total = 0.0

        cur = conn.execute("""
            INSERT INTO replace_bills
            (replaceBillNo, date, customerName, customerNo, oldTotal, newTotal, difference, discount, note)
            VALUES (?, ?, ?, ?, 0, 0, 0, ?, ?)
        """, (replace_no, date_str, customer_name, customer_no, discount, note))
        rb_id = cur.lastrowid

        for it in old_items:
            code = it.get("code") or it.get("barcode") or it.get("barcode_code")
            qty = float(it.get("qty", 1))
            # Frontend sends sell_unit (actual sold price); also accept sell_price aliases.
            sell = float(
                it.get("sell_unit") or it.get("sellUnit")
                or it.get("sell_price") or it.get("sellPrice") or 0
            )
            pi_id = None
            if code:
                try:
                    code_int = int(str(code).strip())
                except ValueError:
                    code_int = None
                if code_int is not None:
                    pi = conn.execute(
                        "SELECT id, sale_price, product_id FROM purchase_item WHERE barcode_no=? AND product_id IS NOT NULL",
                        (code_int,)
                    ).fetchone()
                    if pi:
                        pi_id = pi["id"]
                        if sell <= 0:
                            # Prefer actual sold price from sold_items, not catalog sale_price.
                            sold_row = conn.execute("""
                                SELECT si.unit_sale_price
                                FROM sold_item_barcodes sib
                                JOIN sold_items si ON si.sold_item_id = sib.sold_item_id
                                WHERE sib.barcode_no = ?
                                ORDER BY si.sold_item_id DESC
                                LIMIT 1
                            """, (code_int,)).fetchone()
                            if sold_row and sold_row["unit_sale_price"] is not None:
                                sell = float(sold_row["unit_sale_price"])
                            else:
                                sell = float(pi["sale_price"] or 0)
                        conn.execute("""
                            UPDATE purchase_item SET is_available='available', sold_at=NULL
                            WHERE barcode_no=?
                        """, (code_int,))
                        if pi["product_id"]:
                            conn.execute("""
                                UPDATE products SET sold=GREATEST(sold-1,0), remaining=remaining+1,
                                projected_margin=unit_price*(margin/100.0)*(remaining+1)
                                WHERE product_id=?
                            """, (pi["product_id"],))
                    else:
                        od_row = conn.execute(
                            "SELECT id, uniqee_id, sell_mrp FROM old_data WHERE uniqee_id = ? OR id = ?",
                            (code_int, code_int)
                        ).fetchone()
                        if od_row:
                            conn.execute("""
                                UPDATE old_data
                                SET remaining = remaining + ?,
                                    sold = GREATEST(sold - ?, 0),
                                    is_return = 1
                                WHERE id = ?
                            """, (qty, qty, od_row["id"]))
                            pi_id = od_row["uniqee_id"] or od_row["id"]
                            if sell <= 0:
                                sell = float(od_row["sell_mrp"] or 0)
                            
            line_total = qty * sell
            old_total += line_total
            conn.execute("""
                INSERT INTO replace_bill_items
                (replace_bill_id, side, item, size, qty, sell_price, sell_total, barcode_code, purchase_item_id)
                VALUES (?, 'old', ?, ?, ?, ?, ?, ?, ?)
            """, (rb_id, it.get("item", ""), it.get("size", ""), qty, sell, line_total,
                  str(code) if code else None, pi_id))

        for it in new_items:
            code = it.get("code") or it.get("barcode") or it.get("barcode_code")
            qty = float(it.get("qty", 1))
            sell = float(it.get("sell_price") or it.get("sellPrice") or 0)
            pi_id = None
            if code:
                try:
                    code_int = int(str(code).strip())
                except ValueError:
                    code_int = None
                if code_int is not None:
                    pi = conn.execute(
                        "SELECT id, sale_price, product_id FROM purchase_item WHERE barcode_no=? AND product_id IS NOT NULL AND is_available='available'",
                        (code_int,)
                    ).fetchone()
                    if pi:
                        pi_id = pi["id"]
                        if sell <= 0:
                            sell = float(pi["sale_price"] or 0)
                        conn.execute("""
                            UPDATE purchase_item SET is_available='sold', sold_at=?
                            WHERE barcode_no=?
                        """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), code_int))
                        if pi["product_id"]:
                            conn.execute("""
                                UPDATE products SET sold=sold+1, remaining=remaining-1,
                                projected_margin=unit_price*(margin/100.0)*GREATEST(remaining-1,0)
                                WHERE product_id=?
                            """, (pi["product_id"],))
                    else:
                        od_row = conn.execute(
                            "SELECT id, uniqee_id, sell_mrp FROM old_data WHERE (uniqee_id = ? OR id = ?) AND remaining >= ?",
                            (code_int, code_int, qty)
                        ).fetchone()
                        if od_row:
                            conn.execute("""
                                UPDATE old_data
                                SET remaining = remaining - ?,
                                    sold = sold + ?
                                WHERE id = ?
                            """, (qty, qty, od_row["id"]))
                            pi_id = od_row["uniqee_id"] or od_row["id"]
                            if sell <= 0:
                                sell = float(od_row["sell_mrp"] or 0)
            if discount > 0:
                sell = round2(sell * (1 - discount / 100))
            line_total = qty * sell
            new_total += line_total
            conn.execute("""
                INSERT INTO replace_bill_items
                (replace_bill_id, side, item, size, qty, sell_price, sell_total, barcode_code, purchase_item_id)
                VALUES (?, 'new', ?, ?, ?, ?, ?, ?, ?)
            """, (rb_id, it.get("item", ""), it.get("size", ""), qty, sell, line_total,
                  str(code) if code else None, pi_id))

        diff = new_total - old_total
        conn.execute("""
            UPDATE replace_bills SET oldTotal=?, newTotal=?, difference=? WHERE id=?
        """, (old_total, new_total, diff, rb_id))

        # ── Tally Voucher Auto-Sync ──────────────────────────────────────────
        # Correct accounting for Replace/Exchange:
        #
        #  SALESRET — Sales Dr / Party Cr  (old items returned, via clearing)
        #  SALES    — Party Dr / Sales Cr  (new items given, via clearing)
        #  RECEIPT  — Cash Dr / Party Cr   (customer pays net diff)
        #  PAYMENT  — Party Dr / Cash Cr   (shop refunds net diff)
        #
        # SALESRET + SALES deliberately use the party (clearing) ledger instead
        # of Cash, so Cash is touched ONLY once — through the net RECEIPT/PAYMENT
        # voucher. This prevents the 2× cash double-count bug.
        #
        # After all vouchers:
        #   Party net = (+new_total) − (−old_total) − abs_diff = 0  ✅
        #   Cash net  = abs_diff only                            ✅
        try:
            sales_ledger = conn.execute("SELECT id FROM ledgers WHERE name='Sales'").fetchone()
            cash_ledger  = conn.execute("SELECT id FROM ledgers WHERE name='Cash'").fetchone()
            party_ledger_id = get_or_create_ledger(
                customer_name or "Walk-in Customer", "Sundry Debtors", "Debit", conn
            )

            # 1. SALESRET — customer returns old items
            #    Sales Dr (reverse income) / Party Cr (customer credited)
            if old_total > 0 and sales_ledger:
                VoucherEngine.create_voucher({
                    "voucher_type": "SALESRET",
                    "date": date_str,
                    "reference": replace_no,
                    "narration": f"Replace/Exchange return from {customer_name or 'Walk-in Customer'}",
                    "created_by": "admin",
                    "entries": [
                        {"ledger_id": sales_ledger["id"], "debit": old_total, "credit": 0},
                        {"ledger_id": party_ledger_id,    "debit": 0, "credit": old_total},
                    ]
                }, conn=conn)

            # 2. SALES — new items given to customer
            #    Party Dr (customer owes) / Sales Cr (income)
            if new_total > 0 and sales_ledger:
                VoucherEngine.create_voucher({
                    "voucher_type": "SALES",
                    "date": date_str,
                    "reference": replace_no,
                    "narration": f"Replace/Exchange sale to {customer_name or 'Walk-in Customer'}",
                    "created_by": "admin",
                    "entries": [
                        {"ledger_id": party_ledger_id,    "debit": new_total, "credit": 0},
                        {"ledger_id": sales_ledger["id"], "debit": 0, "credit": new_total},
                    ]
                }, conn=conn)

            # 3. Net differential settlement via Cash (only this voucher touches Cash)
            #    diff > 0 → customer pays extra  → RECEIPT (Cash Dr / Party Cr)
            #    diff < 0 → shop refunds customer → PAYMENT (Party Dr / Cash Cr)
            abs_diff = round2(abs(diff))
            if abs_diff > 0 and cash_ledger:
                if diff > 0:
                    VoucherEngine.create_voucher({
                        "voucher_type": "RECEIPT",
                        "date": date_str,
                        "reference": replace_no,
                        "narration": f"Net amount received for replace {replace_no} from {customer_name or 'Walk-in Customer'}",
                        "created_by": "admin",
                        "entries": [
                            {"ledger_id": cash_ledger["id"], "debit": abs_diff, "credit": 0},
                            {"ledger_id": party_ledger_id,   "debit": 0, "credit": abs_diff},
                        ]
                    }, conn=conn)
                else:
                    VoucherEngine.create_voucher({
                        "voucher_type": "PAYMENT",
                        "date": date_str,
                        "reference": replace_no,
                        "narration": f"Net refund for replace {replace_no} to {customer_name or 'Walk-in Customer'}",
                        "created_by": "admin",
                        "entries": [
                            {"ledger_id": party_ledger_id,   "debit": abs_diff, "credit": 0},
                            {"ledger_id": cash_ledger["id"], "debit": 0, "credit": abs_diff},
                        ]
                    }, conn=conn)
        except Exception as e:
            print(f"Replace/Exchange tally voucher warning: {e}")
        # ────────────────────────────────────────────────────────────────────

        dashboard_cache.refresh_financial_totals(conn)
        conn.commit()
    _trigger_async_cache_recompute()
    return jsonify({"status": "ok", "replaceBillNo": replace_no, "id": rb_id,
                    "oldTotal": old_total, "newTotal": new_total, "difference": diff})


@sales_bp.route("/api/replace_bills", methods=["GET"])
def get_replace_bills():
    date_from = request.args.get("from") or request.args.get("date_from")
    date_to = request.args.get("to") or request.args.get("date_to")
    with get_conn() as conn:
        query = "SELECT * FROM replace_bills WHERE 1=1"
        params = []
        if date_from:
            query += " AND date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND date <= ?"
            params.append(date_to)
        query += " ORDER BY id DESC"
        rows = conn.execute(query, params).fetchall()
    return jsonify([to_camel_row(r) for r in rows])


@sales_bp.route("/api/replace_bill/<int:replace_bill_id>", methods=["GET"])
def api_get_replace_bill(replace_bill_id):
    with get_conn() as conn:
        header = conn.execute("SELECT * FROM replace_bills WHERE id=?", (replace_bill_id,)).fetchone()
        if not header:
            return jsonify({"error": "Not found"}), 404
        items = conn.execute(
            "SELECT * FROM replace_bill_items WHERE replace_bill_id=?", (replace_bill_id,)
        ).fetchall()
    return jsonify({"header": to_camel_row(header), "items": [to_camel_row(i) for i in items]})


@sales_bp.route("/api/replace_bill/<int:replace_bill_id>", methods=["PUT"])
def api_update_replace_bill(replace_bill_id):
    data = request.json or {}
    with get_conn() as conn:
        conn.execute("""
            UPDATE replace_bills SET note=?, discount=? WHERE id=?
        """, (data.get("note", ""), float(data.get("discount", 0) or 0), replace_bill_id))
        conn.commit()
    return jsonify({"status": "ok"})


@sales_bp.route("/api/generate_invoice_no", methods=["GET"])
def generate_invoice_no():
    with get_conn() as conn:
        today = datetime.now().strftime("%Y%m%d")
        result = conn.execute("""
            SELECT COUNT(*) c FROM purchases_header WHERE invoice_no LIKE ?
        """, (f"{today}%",)).fetchone()
        next_num = (result["c"] or 0) + 1
        inv = f"{today}{str(next_num).zfill(3)}"
    return jsonify({"invoiceNo": inv})
