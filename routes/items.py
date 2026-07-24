from datetime import datetime

from flask import Blueprint, request, jsonify

from core.db import get_conn
from routes.sales import create_sale_bill
from routes.purchases import ensure_item_in_master

items_bp = Blueprint("items", __name__)

def decrement_purchase_qty(table, item_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM purchase_items WHERE id=?", (item_id,)).fetchone()
        if not row:
            return None
        row = dict(row)
        qty = float(row["qty"])
        sold = float(row["sold"] if row["sold"] is not None else 0)
        if qty - sold <= 0:
            return "empty"
        new_sold = sold + 1
        conn.execute("""
            UPDATE purchase_items
            SET sold = ?
            WHERE id = ?
        """, (new_sold, item_id))
        return {
            "id": item_id,
            "qty": qty,
            "sold": new_sold,
            "buy_total": row["buy_total"],
            "sell_total": row["sell_total"],
            "profit": row["profit"],
            "item": row["item"],
            "size": row["size"],
            "party": row.get("party", ''),
            "buy": row["buy_price"],
            "margin": row["margin"],
            "sellUnit": row["sell_price"]
        }

def mark_barcode_sold(code):
    with get_conn() as conn:
        c = conn.execute(
            "UPDATE barcodes SET status='sold', sold_at=? WHERE code=? AND status='available'",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), code)
        )
    return c.rowcount > 0

@items_bp.route("/api/items", methods=["GET"])
def api_get_items():
    """
    Return the Items Master list, enriched with live stock numbers
    (purchase stock, sold, remaining/available stock) calculated from
    purchase_items, matched by item name + size.

    Pagination is opt-in: pass ?page=&limit= for a "load next 100" style
    UI (response becomes {items, total, page, limit}). Without those
    params the response is unchanged (plain list), same convention as
    /api/reports/purchases and /api/reports/sales.
    """
    search = request.args.get("search", "")
    page = request.args.get("page", type=int)
    limit = request.args.get("limit", type=int)
    with get_conn() as conn:
        # Self-heal: any item+size combination found in purchase history but
        # missing from the Items Master list gets added automatically. This
        # prevents "Purchase Stock" from showing 0 just because a master entry
        # doesn't line up exactly with the purchase records (e.g. items
        # purchased before this auto-sync feature existed).
        #
        # This used to be a Python loop issuing one query per distinct combo
        # (thousands of round trips), then later a single set-based INSERT --
        # but that still re-scanned the *entire* purchase_items table (100k+
        # rows) on every /api/items load, even when nothing needed healing.
        # That full scan was the single biggest chunk of "Items page lags".
        #
        # Fix: only look at purchase_items rows added since the last check
        # (tracked via app_state.items_synced_upto), since purchase_items is
        # effectively append-only -- new rows are added by new purchases, not
        # by editing old ones. This makes the check O(new rows) instead of
        # O(all rows). Trade-off: if an old purchase_item's item/size text is
        # edited directly in the DB after the fact, it won't be re-checked;
        # that's an acceptable edge case for the normal "new purchase comes
        # in" workflow this exists for.
        last_synced = conn.execute(
            "SELECT items_synced_upto FROM app_state WHERE id=1"
        ).fetchone()
        last_synced_id = last_synced["items_synced_upto"] if last_synced else 0

        conn.execute("""
            INSERT INTO items (name, size, department, hsn, unit, defaultMargin, defaultGST, min_stock, createdAt)
            SELECT DISTINCT TRIM(pi.item), TRIM(COALESCE(pi.size, '')), COALESCE(pi.department, ''),
                   '', '', 0, 0, 0, ?
            FROM purchase_items pi
            WHERE pi.id > ?
              AND pi.item IS NOT NULL AND TRIM(pi.item) != ''
              AND NOT EXISTS (
                  SELECT 1 FROM items i
                  WHERE LOWER(i.name) = LOWER(TRIM(pi.item))
                    AND LOWER(COALESCE(i.size, '')) = LOWER(TRIM(COALESCE(pi.size, '')))
              )
        """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), last_synced_id))

        max_id_row = conn.execute("SELECT MAX(id) as max_id FROM purchase_items").fetchone()
        new_max_id = max_id_row["max_id"] or 0
        if new_max_id > last_synced_id:
            conn.execute(
                "UPDATE app_state SET items_synced_upto = ? WHERE id = 1",
                (new_max_id,)
            )
        conn.commit()

        query = "SELECT * FROM items WHERE 1=1"
        params = []
        if search:
            query += " AND name LIKE ?"
            params.append(f"%{search}%")

        total = None
        if page and limit:
            count_row = conn.execute(query.replace("SELECT *", "SELECT COUNT(*)", 1), params).fetchone()
            total = count_row[0]

        query += " ORDER BY id DESC"
        if page and limit:
            query += " LIMIT ? OFFSET ?"
            params = params + [limit, (page - 1) * limit]
        item_rows = conn.execute(query, params).fetchall()

        # Aggregate purchased / sold quantities AND projected profit (in rupees)
        # on the remaining unsold stock, grouped by item name + size.
        agg_rows = conn.execute("""
            SELECT item, size,
                   SUM(qty) as purchased,
                   SUM(sold) as sold,
                   SUM((qty - sold) * (sell_price - buy_price)) as projectedMargin
            FROM purchase_items
            GROUP BY LOWER(item), LOWER(COALESCE(size, ''))
        """).fetchall()
        agg_map = {}
        for r in agg_rows:
            key = ((r["item"] or "").strip().lower(), (r["size"] or "").strip().lower())
            agg_map[key] = {
                "purchased": r["purchased"] or 0,
                "sold": r["sold"] or 0,
                "projectedMargin": r["projectedMargin"] or 0
            }

        result = []
        for row in item_rows:
            d = dict(row)
            key = ((d.get("name") or "").strip().lower(), (d.get("size") or "").strip().lower())
            stats = agg_map.get(key, {"purchased": 0, "sold": 0, "projectedMargin": 0})
            purchased = stats["purchased"]
            sold = stats["sold"]
            d["purchaseStock"] = purchased
            d["sold"] = sold
            d["remainingStock"] = purchased - sold
            d["projectedMargin"] = stats["projectedMargin"]
            result.append(d)
    if page and limit:
        return jsonify({"items": result, "total": total, "page": page, "limit": limit})
    return jsonify(result)


@items_bp.route("/api/items", methods=["POST"])
def api_create_item():
    """Create a new item (name + size combination) in the Items Master list."""
    data = request.json or {}
    name = (data.get("name") or "").strip()
    size = (data.get("size") or "").strip()
    if not name:
        return jsonify({"error": "Item name required"}), 400
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM items WHERE LOWER(name) = LOWER(?) AND LOWER(COALESCE(size, '')) = LOWER(?)",
            (name, size)
        ).fetchone()
        if existing:
            return jsonify({"error": "Item with this name and size already exists"}), 400
        cur = conn.execute("""
            INSERT INTO items
            (name, size, department, hsn, unit, defaultMargin, defaultGST, min_stock, createdAt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            name,
            size,
            (data.get("department") or "").strip(),
            (data.get("hsn") or "").strip(),
            (data.get("unit") or "").strip(),
            float(data.get("defaultMargin") or 0),
            float(data.get("defaultGST") or 0),
            float(data.get("min_stock") or 0),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        conn.commit()
        return jsonify({"status": "ok", "id": cur.lastrowid})

@items_bp.route("/api/items/<int:item_id>", methods=["PUT"])
def api_update_item(item_id):
    """Update an existing item by ID."""
    data = request.json or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Item name required"}), 400
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return jsonify({"error": "Item not found"}), 404
        conn.execute("""
            UPDATE items
            SET name = ?, size = ?, department = ?, hsn = ?, unit = ?,
                defaultMargin = ?, defaultGST = ?, min_stock = ?
            WHERE id = ?
        """, (
            name,
            (data.get("size") or "").strip(),
            (data.get("department") or "").strip(),
            (data.get("hsn") or "").strip(),
            (data.get("unit") or "").strip(),
            float(data.get("defaultMargin") or 0),
            float(data.get("defaultGST") or 0),
            float(data.get("min_stock") or 0),
            item_id
        ))
        conn.commit()
    return jsonify({"status": "ok"})


@items_bp.route("/api/items/<int:item_id>", methods=["DELETE"])
def api_delete_item(item_id):
    """Delete an item by ID."""
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return jsonify({"error": "Item not found"}), 404
        conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        conn.commit()
    return jsonify({"status": "ok"})


@items_bp.route("/api/items/stock", methods=["GET"])
def api_items_stock():
    search = request.args.get('search', '').strip()

    # Pagination is opt-in: pass ?page=&limit= to avoid pulling every
    # distinct item's stock valuation over the network in one go (same
    # convention as /api/entries and /api/reports/purchases). Without those
    # params the response is unchanged (plain list) for existing callers.
    page = request.args.get('page', type=int)
    limit = request.args.get('limit', type=int)

    with get_conn() as conn:
        where = ""
        params = []
        if search:
            where = "WHERE item LIKE ?"
            params.append(f"%{search}%")

        base_query = f"""
            SELECT item,
                   department,
                   SUM(qty - sold) as stock,
                   SUM((qty - sold) * buy_price) as stockValue
            FROM purchase_items
            {where}
            GROUP BY item
        """

        # Total item count + grand stock value computed in SQL over every
        # matching item, not just whatever page is being shown -- same
        # approach as /api/reports/profit's SQL-computed grand totals.
        totals_row = conn.execute(f"""
            SELECT COUNT(*) as cnt, COALESCE(SUM(stockValue), 0) as total_value
            FROM ({base_query})
        """, params).fetchone()
        total_items = totals_row['cnt']
        total_value = totals_row['total_value'] or 0

        query = base_query + " ORDER BY item COLLATE NOCASE ASC"
        if page and limit:
            offset = (page - 1) * limit
            query += " LIMIT ? OFFSET ?"
            params = params + [limit, offset]

        rows = conn.execute(query, params).fetchall()

        # Only look up department/unit overrides for the items on this page,
        # instead of loading the entire Items Master table on every request.
        item_names = [r['item'] for r in rows]
        item_meta = {}
        if item_names:
            placeholders = ",".join("?" for _ in item_names)
            item_meta = {
                r['name']: {'department': r['department'], 'unit': r['unit']}
                for r in conn.execute(
                    f"SELECT name, department, unit FROM items WHERE name IN ({placeholders})",
                    item_names
                ).fetchall()
            }

        result = []
        for r in rows:
            name = r['item']
            stock = r['stock'] or 0
            stock_value = r['stockValue'] or 0
            meta = item_meta.get(name, {})
            avg_rate = (stock_value / stock) if stock else 0
            result.append({
                "name": name,
                "department": meta.get('department') or r['department'] or '',
                "unit": meta.get('unit') or '',
                "stock": stock,
                "avgBuyRate": avg_rate,
                "stockValue": stock_value
            })

    if page and limit:
        return jsonify({"items": result, "total": total_items, "totalValue": total_value, "page": page, "limit": limit})
    return jsonify(result)

@items_bp.route("/api/barcode_lookup", methods=["GET"])
def barcode_lookup():
    code = request.args.get("code", "").strip()
    if not code:
        return jsonify({"status": "invalid", "message": "Code required"}), 400
    with get_conn() as conn:
        bc = conn.execute("SELECT * FROM barcodes WHERE code=?", (code,)).fetchone()
        if not bc:
            return jsonify({"status": "not_found", "message": "Barcode not found"}), 404
        bc = dict(bc)
        if bc["status"] == "sold":
            return jsonify({"status": "already_sold", "message": f"Barcode {code} already sold."}), 200
        return jsonify({
            "status": "ok",
            "barcode": {
                "code": bc["code"], "item": bc["product_name"], "size": bc["size"],
                "party": bc["party"], "sell_unit": bc["sell_price"],
                "buy_unit": bc["buy_price"], "margin": bc["margin"],
                "purchase_item_id": bc["purchase_item_id"]
            }
        })

@items_bp.route("/api/barcode_lookup_sold", methods=["GET"])
def barcode_lookup_sold():
    """
    Look up a barcode that should currently be marked 'sold' — used by the
    Sales > Replace/Exchange flow when scanning the item a customer is
    returning. Returns the actual price the customer was charged (from the
    original sale_items row) so the exchange difference is calculated
    correctly, falling back to the barcode's stored sell price if the
    original sale row can't be found.
    """
    code = request.args.get("code", "").strip()
    if not code:
        return jsonify({"status": "invalid", "message": "Code required"}), 400
    with get_conn() as conn:
        bc = conn.execute("SELECT * FROM barcodes WHERE code=?", (code,)).fetchone()
        if not bc:
            return jsonify({"status": "not_found", "message": "Barcode not found"}), 404
        bc = dict(bc)
        if bc["status"] != "sold":
            return jsonify({"status": "not_sold", "message": f"Barcode {code} is not a sold item. It cannot be returned."}), 200

        si = conn.execute("""
            SELECT si.sell_price, s.bill_no, s.customer_name
            FROM sale_items si JOIN sales s ON s.id = si.sale_id
            WHERE si.barcode_code = ?
            ORDER BY si.id DESC LIMIT 1
        """, (code,)).fetchone()
        sell_unit = si["sell_price"] if si else bc["sell_price"]

        return jsonify({
            "status": "ok",
            "barcode": {
                "code": bc["code"], "item": bc["product_name"], "size": bc["size"],
                "party": bc["party"], "sell_unit": sell_unit,
                "buy_unit": bc["buy_price"], "margin": bc["margin"],
                "purchase_item_id": bc["purchase_item_id"],
                "originalBillNo": si["bill_no"] if si else None,
                "originalCustomer": si["customer_name"] if si else None
            }
        })

def _row_to_barcode_dict(bc):
    """Shared shape used by every barcode-style API response."""
    return {
        "code": bc["code"], "item": bc["product_name"], "size": bc["size"],
        "party": bc["party"], "sell_unit": bc["sell_price"],
        "buy_unit": bc["buy_price"], "margin": bc["margin"],
        "purchase_item_id": bc["purchase_item_id"]
    }


@items_bp.route("/api/product_search", methods=["GET"])
def product_search():
    """
    Live search used by the Sale entry and Replace/Exchange barcode inputs
    so the user can type a barcode number OR a product name and get a
    temporary list of matching products (name, size, price, party) to pick
    from. Matches are grouped by purchase_item_id (one row per stock
    batch), since the same product/size/party/price combo can have many
    individual barcode units.
    """
    query = request.args.get("query", "").strip()
    status = request.args.get("status", "available")
    if status not in ("available", "sold"):
        status = "available"
    if len(query) < 2:
        return jsonify({"status": "ok", "matches": []})

    with get_conn() as conn:
        # An exact barcode code match is treated as a single, precise result.
        exact = conn.execute(
            "SELECT * FROM barcodes WHERE code = ? AND status = ?", (query, status)
        ).fetchone()
        if exact:
            return jsonify({"status": "ok", "matches": [_row_to_barcode_dict(dict(exact))]})

        rows = conn.execute("""
            SELECT * FROM barcodes
            WHERE status = ? AND (product_name LIKE ? OR code LIKE ?)
            ORDER BY product_name COLLATE NOCASE, party COLLATE NOCASE
        """, (status, f"%{query}%", f"%{query}%")).fetchall()

        seen_batches = set()
        matches = []
        for r in rows:
            r = dict(r)
            batch_key = r["purchase_item_id"]
            if batch_key in seen_batches:
                continue
            seen_batches.add(batch_key)
            matches.append(_row_to_barcode_dict(r))
            if len(matches) >= 30:
                break

        return jsonify({"status": "ok", "matches": matches})


@items_bp.route("/api/barcode_by_item", methods=["GET"])
def barcode_by_item():
    """
    Given a purchase_item_id (a stock batch picked from the product_search
    suggestion list), return one of its barcodes that hasn't been used yet
    in the current cart (the `exclude` list of already-added codes) so
    repeated "Add" clicks on the same searched product each claim a
    different physical unit.
    """
    purchase_item_id = request.args.get("purchase_item_id", type=int)
    status = request.args.get("status", "available")
    exclude = request.args.get("exclude", "").strip()
    exclude_codes = [c for c in exclude.split(",") if c]

    if status not in ("available", "sold"):
        status = "available"
    if not purchase_item_id:
        return jsonify({"status": "invalid", "message": "purchase_item_id required"}), 400

    with get_conn() as conn:
        sql = "SELECT * FROM barcodes WHERE purchase_item_id = ? AND status = ?"
        params = [purchase_item_id, status]
        if exclude_codes:
            placeholders = ",".join("?" for _ in exclude_codes)
            sql += f" AND code NOT IN ({placeholders})"
            params += exclude_codes
        sql += " ORDER BY id LIMIT 1"

        bc = conn.execute(sql, params).fetchone()
        if not bc:
            return jsonify({"status": "not_found", "message": "No more available units of this product."}), 404

        return jsonify({"status": "ok", "barcode": _row_to_barcode_dict(dict(bc))})


@items_bp.route("/api/used_codes", methods=["GET"])
def get_used_codes():
    with get_conn() as conn:
        rows = conn.execute("SELECT code FROM barcodes WHERE status='sold'").fetchall()
    return jsonify([r["code"] for r in rows])

@items_bp.route("/api/sell_scanned", methods=["POST"])
def sell_scanned():
    data = request.json or {}
    customer_name = data.get("customerName", "").strip()
    customer_no = data.get("customerNo", "").strip()
    payment_mode = data.get("paymentMode", "Cash")
    bill_no = data.get("billNo", "").strip()
    discount = float(data.get("discount", 0) or 0)
    sell_mode = data.get("sellMode", "cash")
    items = data.get("items", [])

    if not items:
        return jsonify({"status": "invalid", "message": "No items to sell."}), 400

    errors = []
    sold = []
    sale_items = []

    for itm in items:
        scanned_codes = itm.get("scanned_codes") or [str(itm.get("code", "")).strip()]
        qty = int(itm.get("qty", 1) or 1)

        item_name = None
        item_size = None
        buy_price = None
        margin = None
        purchase_id = None

        for code in scanned_codes:
            code = str(code).strip()
            with get_conn() as conn:
                bc = conn.execute("SELECT * FROM barcodes WHERE code=?", (code,)).fetchone()
                if not bc:
                    errors.append(f"Barcode {code} not found.")
                    continue
                bc = dict(bc)
                if bc["status"] == "sold":
                    errors.append(f"Barcode {code} already sold.")
                    continue

                item_name = bc["product_name"]
                item_size = bc["size"]
                buy_price = bc["buy_price"]
                margin = bc["margin"]
                purchase_id = bc["purchase_item_id"]

                conn.execute(
                    "UPDATE purchase_items SET sold = sold + 1 WHERE id = ?",
                    (purchase_id,)
                )
                conn.execute(
                    "UPDATE barcodes SET status='sold', sold_at=? WHERE code=? AND status='available'",
                    (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), code)
                )
                conn.commit()
                sold.append(code)

        if item_name:
            sale_items.append({
                'item': item_name,
                'size': item_size,
                'qty': len(scanned_codes),
                'buy_price': buy_price,
                'margin': margin,
                'code': scanned_codes[0]
            })

    if errors and not sold:
        return jsonify({"status": "error", "errors": errors}), 400

    if sale_items:
        header = {
            'customer_name': customer_name,
            'customer_no': customer_no,
            'bill_no': bill_no,
            'payment_mode': payment_mode,
            'discount': discount,
            'date': datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        create_sale_bill(header, sale_items, sell_mode)

    return jsonify({"status": "ok", "sold": sold, "errors": errors})

@items_bp.route("/api/barcodes/purchase/<int:purchase_item_id>", methods=["GET"])
def get_barcodes_by_purchase_item(purchase_item_id):
    with get_conn() as conn:
        rows = conn.execute("SELECT code, status FROM barcodes WHERE purchase_item_id = ? ORDER BY id", (purchase_item_id,)).fetchall()
    return jsonify([dict(r) for r in rows])

@items_bp.route("/api/barcodes/by_purchase/<int:purchase_id>", methods=["GET"])
def get_barcodes_by_purchase(purchase_id):
    """Return all barcodes for a purchase grouped by item+size, with sell_price."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT pi.id as purchase_item_id, pi.item, pi.size, pi.sell_price,
                   b.code, b.status
            FROM purchase_items pi
            JOIN barcodes b ON b.purchase_item_id = pi.id
            WHERE pi.purchase_id = ?
            ORDER BY pi.id, b.id
        """, (purchase_id,)).fetchall()
    groups = {}
    order = []
    for r in rows:
        pid = r["purchase_item_id"]
        if pid not in groups:
            groups[pid] = {
                "purchase_item_id": pid,
                "item": r["item"],
                "size": r["size"],
                "sell_price": r["sell_price"],
                "barcodes": []
            }
            order.append(pid)
        groups[pid]["barcodes"].append({"code": r["code"], "status": r["status"]})
    return jsonify([groups[pid] for pid in order])

@items_bp.route("/api/barcodes/next", methods=["GET"])
def get_next_barcode():
    with get_conn() as conn:
        result = conn.execute("SELECT last_number FROM barcode_sequence WHERE id = 1").fetchone()
        next_num = (result[0] if result else 9999) + 1
        return jsonify({"next_code": str(next_num).zfill(5)})
