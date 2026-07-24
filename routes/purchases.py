from datetime import datetime

from flask import Blueprint, request, jsonify

from core.db import get_conn

purchases_bp = Blueprint("purchases", __name__)

def ensure_item_in_master(name, size, department, conn):
    """
    Make sure the item (matched by name + size) exists in the Items Master list.
    - If an item with this exact name AND size already exists (case-insensitive),
      do nothing. Its purchased/sold/remaining stock is calculated live from
      purchase_items, not stored on the Items Master row.
    - If no item with this name + size combination exists yet, create a new
      Items Master entry. A different size for the same name is treated as a
      different item (e.g. "T-shirt" size M vs "T-shirt" size L).
    """
    name = (name or "").strip()
    if not name:
        return
    size = (size or "").strip()
    existing = conn.execute(
        "SELECT id FROM items WHERE LOWER(name) = LOWER(?) AND LOWER(COALESCE(size, '')) = LOWER(?)",
        (name, size)
    ).fetchone()
    if existing:
        return
    conn.execute("""
        INSERT INTO items (name, size, department, hsn, unit, defaultMargin, defaultGST, min_stock, createdAt)
        VALUES (?, ?, ?, '', '', 0, 0, 0, ?)
    """, (
        name,
        size,
        department or '',
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))


def ensure_party_in_master(name, seller_no, address, gst_no, conn):
    """
    Purchase bill banate waqt party Parties tab me auto-create ho jaye.
    - Agar party (case-insensitive) already exist karti hai to kuch nahi karte
      (existing party record ko touch/overwrite nahi karte) — sirf naya hone
      par hi create karte hain.
    - Warna naya party record (GST no. samet) bana dete hain jo /api/parties
      (Parties tab) me turant dikhega.
    """
    name = (name or "").strip()
    if not name:
        return
    existing = conn.execute(
        "SELECT id FROM parties WHERE LOWER(name) = LOWER(?)", (name,)
    ).fetchone()
    if existing:
        return
    conn.execute(
        "INSERT INTO parties (name, seller_no, address, gst_no) VALUES (?, ?, ?, ?)",
        (name, seller_no or '', address or '', gst_no or '')
    )


def create_purchase_bill(header_data, items, mode):
    """
    Inserts a purchase header and its items into the new schema.
    Returns the purchase ID.
    """
    with get_conn() as conn:
        # Insert header
        cur = conn.execute("""
            INSERT INTO purchases
            (invoice_no, party, seller_no, seller_address, seller_gst_no, date, department, mode,
             cgst_rate, sgst_rate, igst_rate, discount, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            header_data.get('invoice_no', ''),
            header_data.get('party', ''),
            header_data.get('seller_no', ''),
            header_data.get('seller_address', ''),
            header_data.get('gst_no', ''),
            header_data.get('date', datetime.now().strftime("%Y-%m-%d %H:%M")),
            header_data.get('department', ''),
            mode,
            header_data.get('cgst', 0),
            header_data.get('sgst', 0),
            header_data.get('igst', 0),
            float(header_data.get('discount', 0) or 0),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        purchase_id = cur.lastrowid

        # Purchase party ko Parties tab me auto-create karo (agar already nahi hai)
        ensure_party_in_master(
            header_data.get('party', ''),
            header_data.get('seller_no', ''),
            header_data.get('seller_address', ''),
            header_data.get('gst_no', ''),
            conn
        )

        total_buy = 0
        total_sell = 0
        total_with_gst = 0

        # Supplier discount (%) — reduces the actual purchase cost / amount
        # payable to the party only. It intentionally does NOT change the
        # sell price, which stays based on the price entered per item.
        discount_pct = float(header_data.get('discount', 0) or 0)

        # Insert items and generate barcodes
        for item in items:
            # Auto-sync this item+size into the Items Master list (no duplicate if it already exists)
            ensure_item_in_master(
                item.get('item', ''),
                item.get('size', ''),
                item.get('department', '') or header_data.get('department', ''),
                conn
            )

            qty = float(item.get('qty', 0))
            buy = float(item.get('buy', 0))  # price as entered — used for margin/sell price, unaffected by discount
            margin = float(item.get('margin', 0))
            cgst = float(item.get('cgst', 0))
            sgst = float(item.get('sgst', 0))
            igst = float(item.get('igst', 0))
            explicit_sell = float(item.get('sell_price', 0) or 0)
            # Agar user ne sell price directly type kiya hai, wahi use karo;
            # warna margin se calculate karke nearest-5 round karo (purana behaviour)
            sell_price = explicit_sell if explicit_sell > 0 else round(buy * (1 + margin / 100) / 5) * 5
            sell_total = qty * sell_price

            # Actual cost after the supplier discount — this drives buy_total,
            # profit, GST, the stored buy_price, and the amount payable to the party.
            effective_buy = buy * (1 - discount_pct / 100)
            buy_total = qty * effective_buy
            profit = sell_total - buy_total
            total_with_gst_item = buy_total * (1 + (cgst + sgst + igst) / 100)

            cur_item = conn.execute("""
                INSERT INTO purchase_items
                (purchase_id, item, size, qty, sold, buy_price, original_buy_price, margin, sell_price,
                 buy_total, sell_total, profit, cgst, sgst, igst, total_with_gst, department)
                VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                purchase_id,
                item.get('item', ''),
                item.get('size', ''),
                qty,
                effective_buy,
                buy,
                margin,
                sell_price,
                buy_total,
                sell_total,
                profit,
                cgst,
                sgst,
                igst,
                total_with_gst_item,
                item.get('department', '')
            ))
            item_id = cur_item.lastrowid

            total_buy += buy_total
            total_sell += sell_total
            total_with_gst += total_with_gst_item

            # Generate barcodes for each unit. Rounded (not truncated) so a
            # fractional qty like 2.5 still gets 3 barcodes instead of
            # silently losing the last half-unit with no warning.
            for _ in range(round(qty)):
                conn.execute("UPDATE barcode_sequence SET last_number = last_number + 1 WHERE id = 1")
                seq = conn.execute("SELECT last_number FROM barcode_sequence WHERE id = 1").fetchone()
                code = str(seq[0]).zfill(5)
                conn.execute("""
                    INSERT INTO barcodes
                    (code, purchase_item_id, product_name, size, party, sell_price, buy_price, margin, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'available', ?)
                """, (
                    code,
                    item_id,
                    item.get('item', ''),
                    item.get('size', ''),
                    header_data.get('party', ''),
                    sell_price,
                    effective_buy,
                    margin,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ))

        # Update header totals
        conn.execute("""
            UPDATE purchases
            SET total_buy = ?, total_sell = ?, total_with_gst = ?
            WHERE id = ?
        """, (total_buy, total_sell, total_with_gst, purchase_id))

        # If mode is credit, create borrow record
        if mode == 'credit':
            conn.execute("""
                INSERT INTO purchase_borrow
                (purchase_id, invoice_no, party_name, party_phone, total_amount, paid_amount, balance_amount, status)
                VALUES (?, ?, ?, ?, ?, 0, ?, 'Pending')
            """, (
                purchase_id,
                header_data.get('invoice_no', ''),
                header_data.get('party', ''),
                header_data.get('seller_no', ''),
                total_with_gst,
                total_with_gst
            ))

        conn.commit()
        return purchase_id

def update_purchase_bill(purchase_id, header_data, items):
    """
    Update an existing purchase bill.
    - header_data: dict with party, seller_no, seller_address, invoice_no, date, department, cgst, sgst, igst
    - items: list of dict, each with 'id' (purchase_items.id) and updated fields:
        item, size, qty, buy (buy_price), margin, sell_price, cgst, sgst, igst
    - Returns updated purchase_id on success.
    - Handles barcode adjustments: increase qty → generate new barcodes; decrease qty → remove unsold barcodes.
    """
    with get_conn() as conn:
        # Get current header
        cur_header = conn.execute("SELECT * FROM purchases WHERE id = ?", (purchase_id,)).fetchone()
        if not cur_header:
            raise ValueError(f"Purchase {purchase_id} not found")

        # Discount % from the edit form — falls back to whatever was saved
        # on this bill previously if the field wasn't sent at all.
        discount_pct = float(header_data.get('discount', cur_header['discount'] or 0) or 0)

        # Update header
        conn.execute("""
            UPDATE purchases SET
                invoice_no = ?,
                party = ?,
                seller_no = ?,
                seller_address = ?,
                seller_gst_no = ?,
                date = ?,
                department = ?,
                cgst_rate = ?,
                sgst_rate = ?,
                igst_rate = ?,
                discount = ?
            WHERE id = ?
        """, (
            header_data.get('invoice_no', ''),
            header_data.get('party', ''),
            header_data.get('seller_no', ''),
            header_data.get('seller_address', ''),
            header_data.get('gst_no', ''),
            header_data.get('date', datetime.now().strftime("%Y-%m-%d %H:%M")),
            header_data.get('department', ''),
            float(header_data.get('cgst', 0)),
            float(header_data.get('sgst', 0)),
            float(header_data.get('igst', 0)),
            discount_pct,
            purchase_id
        ))

        # Agar bill edit karte waqt party badli/nayi hai to use bhi auto-create karo
        ensure_party_in_master(
            header_data.get('party', ''),
            header_data.get('seller_no', ''),
            header_data.get('seller_address', ''),
            header_data.get('gst_no', ''),
            conn
        )

        # Keep track of existing item IDs to detect deletions later
        existing_item_ids = set()
        total_buy = 0
        total_sell = 0
        total_with_gst = 0

        for item_data in items:
            item_id = item_data.get('id')
            if item_id:
                existing_item_ids.add(item_id)
                # Update existing item
                item = conn.execute("SELECT * FROM purchase_items WHERE id = ? AND purchase_id = ?",
                                    (item_id, purchase_id)).fetchone()
                if not item:
                    raise ValueError(f"Item {item_id} not found in this purchase")
                old_qty = float(item['qty'])
                new_qty = float(item_data.get('qty', old_qty))
                # buy = the original per-unit price as typed (before discount)
                # — same meaning as 'buy' in create_purchase_bill. Falls back
                # to the saved original_buy_price, not the already-discounted
                # buy_price, so re-saving without touching this field doesn't
                # silently double-apply or drop the discount.
                buy = float(item_data.get('buy', item['original_buy_price'] if item['original_buy_price'] is not None else item['buy_price']))
                margin = float(item_data.get('margin', item['margin']))
                sell_price = float(item_data.get('sell_price', 0))
                cgst = float(item_data.get('cgst', item['cgst'] or 0))
                sgst = float(item_data.get('sgst', item['sgst'] or 0))
                igst = float(item_data.get('igst', item['igst'] or 0))

                # Sell price is always based on the original price entered —
                # a supplier discount never reduces sell price or margin.
                if sell_price > 0:
                    sell_unit = sell_price
                else:
                    sell_unit = round(buy * (1 + margin / 100) / 5) * 5
                sell_total = new_qty * sell_unit

                # Actual cost after the supplier discount — drives buy_total,
                # profit, GST and the amount payable to the party.
                effective_buy = buy * (1 - discount_pct / 100)
                buy_total = new_qty * effective_buy
                profit = sell_total - buy_total
                total_with_gst_item = buy_total * (1 + (cgst + sgst + igst) / 100)

                # Update item
                conn.execute("""
                    UPDATE purchase_items SET
                        item = ?,
                        size = ?,
                        qty = ?,
                        buy_price = ?,
                        original_buy_price = ?,
                        margin = ?,
                        sell_price = ?,
                        buy_total = ?,
                        sell_total = ?,
                        profit = ?,
                        cgst = ?,
                        sgst = ?,
                        igst = ?,
                        total_with_gst = ?,
                        department = ?
                    WHERE id = ?
                """, (
                    item_data.get('item', item['item']),
                    item_data.get('size', item['size']),
                    new_qty,
                    effective_buy,
                    buy,
                    margin,
                    sell_unit,
                    buy_total,
                    sell_total,
                    profit,
                    cgst,
                    sgst,
                    igst,
                    total_with_gst_item,
                    item_data.get('department', item['department']),
                    item_id
                ))

                # Handle barcode quantity changes
                qty_diff = new_qty - old_qty
                if qty_diff > 0:
                    # Increase qty: generate new barcodes
                    for _ in range(round(qty_diff)):
                        conn.execute("UPDATE barcode_sequence SET last_number = last_number + 1 WHERE id = 1")
                        seq = conn.execute("SELECT last_number FROM barcode_sequence WHERE id = 1").fetchone()
                        code = str(seq[0]).zfill(5)
                        conn.execute("""
                            INSERT INTO barcodes
                            (code, purchase_item_id, product_name, size, party, sell_price, buy_price, margin, status, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'available', ?)
                        """, (
                            code,
                            item_id,
                            item_data.get('item', item['item']),
                            item_data.get('size', item['size']),
                            header_data.get('party', ''),
                            sell_unit,
                            effective_buy,
                            margin,
                            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        ))
                elif qty_diff < 0:
                    # Decrease qty: remove unsold barcodes
                    remove_count = round(-qty_diff)
                    unsold = conn.execute("""
                        SELECT code FROM barcodes
                        WHERE purchase_item_id = ? AND status = 'available'
                        ORDER BY id
                    """, (item_id,)).fetchall()
                    if len(unsold) < remove_count:
                        raise ValueError(
                            f"Cannot reduce qty by {remove_count} for item '{item_data.get('item', item['item'])}' – "
                            f"only {len(unsold)} unsold units available."
                        )
                    for bc in unsold[:remove_count]:
                        conn.execute("DELETE FROM barcodes WHERE code = ?", (bc['code'],))

                total_buy += buy_total
                total_sell += sell_total
                total_with_gst += total_with_gst_item

            else:
                # New item (no id) – add as new purchase_item and generate barcodes
                # This is optional; we'll support adding new items during edit
                qty = float(item_data.get('qty', 0))
                buy = float(item_data.get('buy', 0))
                margin = float(item_data.get('margin', 0))
                sell_price = float(item_data.get('sell_price', 0))
                cgst = float(item_data.get('cgst', 0))
                sgst = float(item_data.get('sgst', 0))
                igst = float(item_data.get('igst', 0))
                if qty <= 0 or buy <= 0:
                    continue  # skip invalid

                # Auto-sync this item+size into the Items Master list (no duplicate if it already exists)
                ensure_item_in_master(
                    item_data.get('item', ''),
                    item_data.get('size', ''),
                    item_data.get('department', '') or header_data.get('department', ''),
                    conn
                )

                sell_unit = sell_price if sell_price > 0 else round(buy * (1 + margin / 100) / 5) * 5
                sell_total = qty * sell_unit

                # Same discount logic as create_purchase_bill / existing items above.
                effective_buy = buy * (1 - discount_pct / 100)
                buy_total = qty * effective_buy
                profit = sell_total - buy_total
                total_with_gst_item = buy_total * (1 + (cgst + sgst + igst) / 100)

                cur = conn.execute("""
                    INSERT INTO purchase_items
                    (purchase_id, item, size, qty, sold, buy_price, original_buy_price, margin, sell_price,
                     buy_total, sell_total, profit, cgst, sgst, igst, total_with_gst, department)
                    VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    purchase_id,
                    item_data.get('item', ''),
                    item_data.get('size', ''),
                    qty,
                    effective_buy,
                    buy,
                    margin,
                    sell_unit,
                    buy_total,
                    sell_total,
                    profit,
                    cgst,
                    sgst,
                    igst,
                    total_with_gst_item,
                    item_data.get('department', '')
                ))
                new_item_id = cur.lastrowid
                existing_item_ids.add(new_item_id)  # to avoid deletion

                # Generate barcodes for new item
                for _ in range(round(qty)):
                    conn.execute("UPDATE barcode_sequence SET last_number = last_number + 1 WHERE id = 1")
                    seq = conn.execute("SELECT last_number FROM barcode_sequence WHERE id = 1").fetchone()
                    code = str(seq[0]).zfill(5)
                    conn.execute("""
                        INSERT INTO barcodes
                        (code, purchase_item_id, product_name, size, party, sell_price, buy_price, margin, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'available', ?)
                    """, (
                        code,
                        new_item_id,
                        item_data.get('item', ''),
                        item_data.get('size', ''),
                        header_data.get('party', ''),
                        sell_unit,
                        effective_buy,
                        margin,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    ))

                total_buy += buy_total
                total_sell += sell_total
                total_with_gst += total_with_gst_item

        # Delete any items that were not in the updated list
        all_item_ids = set(r['id'] for r in conn.execute("SELECT id FROM purchase_items WHERE purchase_id = ?", (purchase_id,)).fetchall())
        to_delete = all_item_ids - existing_item_ids
        for item_id in to_delete:
            # Check if any barcodes are sold
            sold_barcodes = conn.execute("SELECT 1 FROM barcodes WHERE purchase_item_id = ? AND status = 'sold' LIMIT 1", (item_id,)).fetchone()
            if sold_barcodes:
                raise ValueError(f"Cannot delete item with sold units (item_id {item_id}).")
            # Delete barcodes and item
            conn.execute("DELETE FROM barcodes WHERE purchase_item_id = ?", (item_id,))
            conn.execute("DELETE FROM purchase_items WHERE id = ?", (item_id,))

        # Update header totals
        conn.execute("""
            UPDATE purchases
            SET total_buy = ?, total_sell = ?, total_with_gst = ?
            WHERE id = ?
        """, (total_buy, total_sell, total_with_gst, purchase_id))

        # If purchase mode is credit, update borrow record (if exists)
        mode = cur_header['mode']
        if mode == 'credit':
            borrow = conn.execute("SELECT * FROM purchase_borrow WHERE purchase_id = ?", (purchase_id,)).fetchone()
            if borrow:
                new_balance = total_with_gst - borrow['paid_amount']
                new_status = 'Paid' if new_balance <= 0.01 else ('Partial' if borrow['paid_amount'] > 0 else 'Pending')
                conn.execute("""
                    UPDATE purchase_borrow
                    SET total_amount = ?, balance_amount = ?, status = ?, updated_at = ?
                    WHERE purchase_id = ?
                """, (total_with_gst, new_balance, new_status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), purchase_id))

        conn.commit()
        return purchase_id

def get_purchase_bill(purchase_id):
    """Return header and items for a single purchase bill."""
    with get_conn() as conn:
        header = conn.execute("SELECT * FROM purchases WHERE id = ?", (purchase_id,)).fetchone()
        if not header:
            return None
        items = conn.execute("SELECT * FROM purchase_items WHERE purchase_id = ?", (purchase_id,)).fetchall()
        return dict(header), [dict(it) for it in items]

def get_purchase_rows(filters=None, limit=None, offset=None):
    """Returns list of purchase items joined with header, matching old row structure.

    `limit`/`offset` are optional and backward compatible: when omitted, behaves
    exactly as before (returns every matching row).
    """
    with get_conn() as conn:
        query = """
            SELECT
                p.id as purchase_id,
                p.invoice_no,
                p.party,
                p.seller_no,
                p.seller_address,
                p.date,
                p.department,
                p.mode,
                pi.id as item_id,
                pi.item,
                pi.size,
                pi.qty,
                pi.sold,
                pi.buy_price as buy,
                pi.margin,
                pi.sell_price as sellUnit,
                pi.buy_total as buyTotal,
                pi.sell_total as sellTotal,
                pi.profit,
                pi.cgst,
                pi.sgst,
                pi.igst,
                pi.total_with_gst as totalWithGST,
                pi.department as item_dept
            FROM purchases p
            JOIN purchase_items pi ON p.id = pi.purchase_id
            WHERE 1=1
        """
        params = []
        if filters:
            if 'mode' in filters:
                query += " AND p.mode = ?"
                params.append(filters['mode'])
            if 'date_from' in filters:
                query += " AND p.date >= ?"
                params.append(filters['date_from'])
            if 'date_to' in filters:
                query += " AND p.date <= ?"
                params.append(filters['date_to'] + ' 23:59:59')
            if 'party' in filters and filters['party']:
                query += " AND p.party LIKE ?"
                params.append(f"%{filters['party']}%")
            if 'invoice_no' in filters and filters['invoice_no']:
                query += " AND p.invoice_no LIKE ?"
                params.append(f"%{filters['invoice_no']}%")
            if 'item' in filters and filters['item']:
                query += " AND pi.item LIKE ?"
                params.append(f"%{filters['item']}%")
            if 'payment_type' in filters and filters['payment_type']:
                query += " AND p.mode = ?"
                params.append(filters['payment_type'])
            if filters.get('sold_gt_zero'):
                query += " AND pi.sold > 0"
        sort = filters.get('sort', 'date_desc') if filters else 'date_desc'
        if sort == 'date_asc':
            query += " ORDER BY p.date ASC, p.id ASC"
        else:
            query += " ORDER BY p.date DESC, p.id DESC"

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


def get_purchase_stats(filters=None):
    """Count + qty/buyTotal/sellTotal/profit sums for the Reports > Analyze
    stat cards, computed with a single SQL aggregate query instead of
    pulling every matching row (potentially 100k+) over the network just to
    add them up in JS. Same filter set as get_purchase_rows/_count."""
    with get_conn() as conn:
        query = """
            SELECT
                COUNT(*) as cnt,
                COALESCE(SUM(pi.qty), 0) as qty,
                COALESCE(SUM(pi.buy_total), 0) as buyTotal,
                COALESCE(SUM(pi.sell_total), 0) as sellTotal,
                COALESCE(SUM(pi.profit), 0) as profit
            FROM purchases p
            JOIN purchase_items pi ON p.id = pi.purchase_id
            WHERE 1=1
        """
        params = []
        if filters:
            if 'mode' in filters:
                query += " AND p.mode = ?"
                params.append(filters['mode'])
            if 'date_from' in filters:
                query += " AND p.date >= ?"
                params.append(filters['date_from'])
            if 'date_to' in filters:
                query += " AND p.date <= ?"
                params.append(filters['date_to'] + ' 23:59:59')
        row = conn.execute(query, params).fetchone()
        return {
            'count': row['cnt'],
            'qty': row['qty'],
            'buyTotal': row['buyTotal'],
            'sellTotal': row['sellTotal'],
            'profit': row['profit'],
        }


def get_purchase_rows_count(filters=None):
    """Row count for the same filter set as get_purchase_rows, for pagination meta."""
    with get_conn() as conn:
        query = """
            SELECT COUNT(*) as cnt
            FROM purchases p
            JOIN purchase_items pi ON p.id = pi.purchase_id
            WHERE 1=1
        """
        params = []
        if filters:
            if 'mode' in filters:
                query += " AND p.mode = ?"
                params.append(filters['mode'])
            if 'date_from' in filters:
                query += " AND p.date >= ?"
                params.append(filters['date_from'])
            if 'date_to' in filters:
                query += " AND p.date <= ?"
                params.append(filters['date_to'] + ' 23:59:59')
            if 'party' in filters and filters['party']:
                query += " AND p.party LIKE ?"
                params.append(f"%{filters['party']}%")
            if 'invoice_no' in filters and filters['invoice_no']:
                query += " AND p.invoice_no LIKE ?"
                params.append(f"%{filters['invoice_no']}%")
            if 'item' in filters and filters['item']:
                query += " AND pi.item LIKE ?"
                params.append(f"%{filters['item']}%")
            if 'payment_type' in filters and filters['payment_type']:
                query += " AND p.mode = ?"
                params.append(filters['payment_type'])
        return conn.execute(query, params).fetchone()['cnt']

@purchases_bp.route("/api/purchase_bill", methods=["POST"])
def api_purchase_bill():
    try:
        data = request.json
        header = data.get('header', {})
        items = data.get('items', [])
        mode = data.get('mode', 'cash')
        if not items:
            return jsonify({"status": "error", "msg": "No items"}), 400

        purchase_id = create_purchase_bill(header, items, mode)
        return jsonify({"status": "ok", "purchase_id": purchase_id})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "msg": str(e)}), 500

@purchases_bp.route("/api/purchase_bill/<int:purchase_id>", methods=["GET"])
def api_get_purchase_bill(purchase_id):
    result = get_purchase_bill(purchase_id)
    if not result:
        return jsonify({"error": "Purchase not found"}), 404
    header, items = result
    return jsonify({"header": header, "items": items})

@purchases_bp.route("/api/purchase_bill/<int:purchase_id>", methods=["PUT"])
def api_update_purchase_bill(purchase_id):
    try:
        data = request.json
        header = data.get('header', {})
        items = data.get('items', [])
        if not items:
            return jsonify({"status": "error", "msg": "No items"}), 400
        updated_id = update_purchase_bill(purchase_id, header, items)
        return jsonify({"status": "ok", "purchase_id": updated_id})
    except ValueError as e:
        return jsonify({"status": "error", "msg": str(e)}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "msg": str(e)}), 500


@purchases_bp.route("/api/purchase_returns", methods=["GET"])
def get_purchase_returns():
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
                f"SELECT * FROM purchase_returns{where} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [limit, offset]
            ).fetchall()
            total = conn.execute(f"SELECT COUNT(*) as cnt FROM purchase_returns{where}", params).fetchone()['cnt']
            return jsonify({'entries': [dict(r) for r in rows], 'total': total, 'page': page, 'limit': limit})

        rows = conn.execute(f"SELECT * FROM purchase_returns{where} ORDER BY id DESC", params).fetchall()
    return jsonify([dict(r) for r in rows])

@purchases_bp.route("/api/purchase_invoices/search", methods=["GET"])
def api_purchase_invoices_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT pi.id, p.id as purchase_id, p.invoice_no as invoiceNo, p.party as party
            FROM purchase_items pi
            JOIN purchases p ON p.id = pi.purchase_id
            WHERE p.invoice_no LIKE ? OR p.party LIKE ?
            ORDER BY p.id DESC
        """, (f"%{q}%", f"%{q}%")).fetchall()
    result = [dict(r) for r in rows]
    for r in result:
        r["sourceTable"] = "purchase_items"
    return jsonify(result)

@purchases_bp.route("/api/purchase_invoices/<table>/<int:purchase_id>", methods=["GET"])
def api_purchase_invoice_items(table, purchase_id):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT pi.id, pi.item, pi.size, pi.qty, pi.sold, pi.buy_price as buy
            FROM purchase_items pi
            JOIN purchases p ON p.id = pi.purchase_id
            WHERE p.id = ?
        """, (purchase_id,)).fetchall()
    return jsonify([dict(r) for r in rows])

@purchases_bp.route("/api/purchase_return_bill", methods=["POST"])
def api_purchase_return_bill():
    data = request.json or {}
    items = data.get("items", [])
    reason = data.get("reason", "")
    if not items:
        return jsonify({"status": "error", "message": "No items selected"}), 400

    with get_conn() as conn:
        today = datetime.now().strftime("%Y%m%d")
        prefix = f"PR{today}-"
        result = conn.execute("""
            SELECT MAX(CAST(SUBSTR(returnBillNo, LENGTH(?) + 1) AS INTEGER)) as max_num
            FROM purchase_returns WHERE returnBillNo LIKE ? || '%'
        """, (prefix, prefix)).fetchone()
        next_num = (result["max_num"] if result["max_num"] else 0) + 1
        return_bill_no = f"{prefix}{str(next_num).zfill(4)}"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            for it in items:
                pi = conn.execute("""
                    SELECT pi.id, pi.item, pi.size, pi.qty, pi.sold, pi.buy_price,
                           p.party, p.invoice_no, p.department
                    FROM purchase_items pi
                    JOIN purchases p ON p.id = pi.purchase_id
                    WHERE pi.id = ?
                """, (it.get("originalId"),)).fetchone()
                if not pi:
                    continue
                qty = float(it.get("qty", 0))
                buy = pi["buy_price"] or 0
                available = pi["qty"] - pi["sold"]
                if qty > available:
                    raise ValueError(f"Cannot return {qty} units; only {available} unsold units available for item '{pi['item']}'")

                # Reduce qty and delete corresponding available barcodes
                conn.execute("""
                    UPDATE purchase_items
                    SET qty = qty - ?
                    WHERE id = ?
                """, (qty, pi["id"]))

                # Delete that many available barcodes for this purchase_item
                barcodes_to_delete = conn.execute("""
                    SELECT code FROM barcodes
                    WHERE purchase_item_id = ? AND status = 'available'
                    ORDER BY id
                    LIMIT ?
                """, (pi["id"], int(qty))).fetchall()
                for bc in barcodes_to_delete:
                    conn.execute("DELETE FROM barcodes WHERE code = ?", (bc["code"],))

                conn.execute("""
                    INSERT INTO purchase_returns
                    (returnBillNo, date, party, item, size, qty, buy, buyTotal,
                     originalInvoiceNo, originalTable, originalId, reason, department)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    return_bill_no, now, pi["party"], pi["item"], pi["size"], qty,
                    buy, qty * buy, pi["invoice_no"], it.get("originalTable", ""),
                    it.get("originalId"), reason, pi["department"]
                ))
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400
        conn.commit()
    return jsonify({"status": "ok", "returnBillNo": return_bill_no})

@purchases_bp.route("/api/generate_bill_no", methods=["GET"])
def generate_bill_no():
    with get_conn() as conn:
        result = conn.execute("""
            SELECT MAX(CAST(bill_no AS INTEGER)) as max_num
            FROM sales
        """).fetchone()

        next_num = (result["max_num"] or 0) + 1
        bill_no = str(next_num).zfill(4)

    return jsonify({"billNo": bill_no})

@purchases_bp.route("/api/purchase_parties", methods=["GET"])
def get_purchase_parties():
    """Return distinct party names from purchases for datalist suggestions."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT party FROM purchases WHERE party IS NOT NULL AND party != '' ORDER BY party"
        ).fetchall()
    return jsonify([r["party"] for r in rows])
