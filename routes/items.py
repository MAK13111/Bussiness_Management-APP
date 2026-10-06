from datetime import datetime
import threading

from flask import Blueprint, request, jsonify

from core.db import get_conn
from routes.purchases import ensure_item_in_master

items_bp = Blueprint("items", __name__)


def mark_barcode_sold(code):
    with get_conn() as conn:
        try:
            code_int = int(str(code).strip())
        except (TypeError, ValueError):
            return False
        cur = conn.execute("""
            UPDATE purchase_item
            SET is_available='sold', sold_at=?
            WHERE barcode_no=? AND is_available='available' AND product_id IS NOT NULL
        """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), code_int))
        if cur.rowcount:
            pi = conn.execute(
                "SELECT product_id FROM purchase_item WHERE barcode_no=?", (code_int,)
            ).fetchone()
            if pi and pi["product_id"]:
                conn.execute("""
                    UPDATE products SET sold=sold+1, remaining=remaining-1,
                    projected_margin=unit_price*(margin/100.0)*GREATEST(remaining-1,0)
                    WHERE product_id=?
                """, (pi["product_id"],))
            conn.commit()
            return True
        return False


def _sync_items_from_products(conn):
    """Incremental sync: insert any products.item_name+size missing from items in set operations."""
    last = conn.execute(
        "SELECT items_synced_upto FROM app_state WHERE id=1"
    ).fetchone()
    last_id = last["items_synced_upto"] if last else 0

    max_row = conn.execute("SELECT MAX(product_id) as max_id FROM products").fetchone()
    if not max_row or max_row["max_id"] is None or max_row["max_id"] <= last_id:
        return

    max_id = max_row["max_id"]

    conn.execute("""
        INSERT INTO items (name, size, department, hsn, unit, defaultMargin, defaultGST, min_stock, createdAt)
        SELECT DISTINCT TRIM(p.item_name), TRIM(COALESCE(p.size, '')), TRIM(COALESCE(p.department, '')), '', '', 0, 0, 0, NOW()
        FROM products p
        WHERE p.product_id > ? AND p.item_name IS NOT NULL AND TRIM(p.item_name) != '' AND COALESCE(p.status, '') != 'deleted'
          AND NOT EXISTS (
              SELECT 1 FROM items i
              WHERE LOWER(i.name) = LOWER(TRIM(p.item_name))
                AND LOWER(COALESCE(i.size, '')) = LOWER(TRIM(COALESCE(p.size, '')))
          )
    """, (last_id,))

    # Clean up items master rows that have 0 purchase stock and no sales history
    conn.execute("""
        DELETE FROM items
        WHERE id NOT IN (
            SELECT DISTINCT i.id
            FROM items i
            JOIN products p ON LOWER(TRIM(p.item_name)) = LOWER(TRIM(i.name))
                           AND LOWER(TRIM(COALESCE(p.size, ''))) = LOWER(TRIM(COALESCE(i.size, '')))
            WHERE (p.qty > 0 OR p.sold > 0) AND COALESCE(p.status, '') != 'deleted'
        )
        AND id NOT IN (
            SELECT DISTINCT i.id
            FROM items i
            JOIN sold_items si ON LOWER(TRIM(si.item_name)) = LOWER(TRIM(i.name))
                              AND LOWER(TRIM(COALESCE(si.size, ''))) = LOWER(TRIM(COALESCE(i.size, '')))
        )
    """)

    conn.execute(
        "UPDATE app_state SET items_synced_upto=? WHERE id=1", (max_id,)
    )


def _sync_items_from_products_bg():
    """Background wrapper for _sync_items_from_products().
    Gets its own DB connection so it doesn't block the request that triggered it.
    Errors are logged but never re-raised (daemon thread must not crash).
    """
    try:
        with get_conn() as conn:
            _sync_items_from_products(conn)
    except Exception as e:
        print(f"[items sync] background sync error (non-fatal): {e}")


@items_bp.route("/api/items", methods=["GET"])
def api_get_items():
    try:
        page = max(int(request.args.get("page") or 1), 1)
    except (TypeError, ValueError):
        page = 1
    try:
        limit = max(int(request.args.get("limit") or 100), 1)
    except (TypeError, ValueError):
        limit = 100
    search = (request.args.get("search") or "").strip()
    total_param = request.args.get("total", type=int) or request.args.get("known_total", type=int)
    offset = (page - 1) * limit

    with get_conn() as conn:
        # Run the items sync in a background thread so the tab opens instantly.
        # The sync inserts/deletes from the items master table; it is NOT needed
        # to read the current stock list (we query products directly below).
        threading.Thread(target=_sync_items_from_products_bg, daemon=True).start()
        if search:
            like = f"%{search}%"
            total = total_param if (total_param is not None and total_param > 0) else conn.execute("""
                SELECT COUNT(*) as c FROM items
                WHERE name ILIKE ? OR size ILIKE ? OR department ILIKE ?
            """, (like, like, like)).fetchone()["c"]
            items = conn.execute("""
                SELECT * FROM items
                WHERE name ILIKE ? OR size ILIKE ? OR department ILIKE ?
                ORDER BY name, size LIMIT ? OFFSET ?
            """, (like, like, like, limit, offset)).fetchall()
        else:
            total = total_param if (total_param is not None and total_param > 0) else conn.execute("SELECT COUNT(*) as c FROM items").fetchone()["c"]
            items = conn.execute("""
                SELECT * FROM items ORDER BY name, size LIMIT ? OFFSET ?
            """, (limit, offset)).fetchall()

        item_names = tuple(set(it["name"] for it in items if it.get("name")))
        stock_map = {}
        if item_names:
            placeholders = ",".join("?" for _ in item_names)
            stock_rows = conn.execute(f"""
                SELECT item_name,
                       COALESCE(SUM(CASE WHEN qty > 0 THEN qty ELSE 0 END), 0) as purchase_stock,
                       COALESCE(SUM(CASE WHEN qty > 0 THEN sold ELSE 0 END), 0) as sold_qty,
                       COALESCE(SUM(CASE WHEN qty > 0 AND (qty-sold)>0 THEN qty - sold ELSE 0 END), 0) as remaining,
                       COALESCE(SUM(CASE WHEN qty > 0 AND (qty-sold)>0
                            THEN total_buy_price * (qty-sold) / qty ELSE 0 END), 0) as stock_value,
                       COALESCE(SUM(projected_margin), 0) as projected_margin
                FROM products
                WHERE status != 'deleted' AND item_name IN ({placeholders})
                GROUP BY item_name
            """, item_names).fetchall()

            stock_map = {r["item_name"]: r for r in stock_rows}

        result = []
        for it in items:
            d = dict(it)
            s = stock_map.get(it["name"]) or {}
            d["purchaseStock"] = float(s.get("purchase_stock") or 0)
            d["sold"] = float(s.get("sold_qty") or 0)
            d["remainingStock"] = float(s.get("remaining") or 0)
            d["stockValue"] = float(s.get("stock_value") or 0)
            d["projectedMargin"] = float(s.get("projected_margin") or 0)
            result.append(d)
    return jsonify({"items": result, "total": total})


@items_bp.route("/api/items/stock", methods=["GET"])
def api_items_stock():
    try:
        page = max(int(request.args.get("page") or 1), 1)
    except (TypeError, ValueError):
        page = 1
    try:
        limit = max(int(request.args.get("limit") or 100), 1)
    except (TypeError, ValueError):
        limit = 100
    search = (request.args.get("search") or "").strip()
    offset = (page - 1) * limit
    # Client can send a cached total_value from page 1 to avoid re-computing
    # the expensive full-products SUM on every page turn.
    cached_total_value = request.args.get("totalValue", type=float)
    # Client can also send the known total item count (from page 1) to skip
    # the 3-second COUNT(*) scan on every page turn.
    known_total = request.args.get("knownTotal", type=int)

    with get_conn() as conn:
        where_sql = ""
        params = []
        if search:
            where_sql = "WHERE name ILIKE ? OR department ILIKE ?"
            params = [f"%{search}%", f"%{search}%"]

        # COUNT(*) takes 3+ seconds on 500k-row items tables.
        # Skip it on page turns when the client already knows the total.
        if known_total is not None and page > 1:
            total_items = known_total
        else:
            total_items = conn.execute(f"""
                SELECT COUNT(*) as cnt
                FROM items
                {where_sql}
            """, params).fetchone()["cnt"]

        # total_value is a full products table scan (expensive on large tables).
        # Only recompute it on the first page or when a search filter changes;
        # page-turn requests send the cached value from page 1 instead.
        if cached_total_value is not None and page > 1:
            total_value = cached_total_value
        else:
            total_value = float(conn.execute(f"""
                SELECT COALESCE(SUM(total_buy_price * (qty - sold) / NULLIF(qty, 0)), 0) as val
                FROM products
                WHERE qty > 0 AND (qty - sold) > 0
                  AND COALESCE(status, '') != 'deleted'
                  {"AND (item_name ILIKE ? OR department ILIKE ?)" if search else ""}
            """, [f"%{search}%", f"%{search}%"] if search else []).fetchone()["val"] or 0)

        page_items = conn.execute(f"""
            SELECT name as item_name, COALESCE(department, '') as department, COALESCE(unit, 'pcs') as unit
            FROM items
            {where_sql}
            ORDER BY name
            LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()

        item_names = tuple(set(pi["item_name"] for pi in page_items if pi["item_name"]))
        stock_map = {}
        if item_names:
            placeholders = ",".join("?" for _ in item_names)
            s_rows = conn.execute(f"""
                SELECT item_name, COALESCE(department, '') as department,
                       COALESCE(SUM(CASE WHEN qty>0 THEN qty-sold ELSE 0 END),0) AS stock_qty,
                       CASE WHEN SUM(CASE WHEN qty>0 THEN qty-sold ELSE 0 END)>0
                            THEN SUM(CASE WHEN qty>0 AND (qty-sold)>0
                                 THEN total_buy_price*(qty-sold)/qty ELSE 0 END)
                                 / NULLIF(SUM(CASE WHEN qty>0 THEN qty-sold ELSE 0 END),0)
                            ELSE 0 END AS avg_buy_rate,
                       COALESCE(SUM(CASE WHEN qty>0 AND (qty-sold)>0
                            THEN total_buy_price*(qty-sold)/qty ELSE 0 END),0) AS stock_value
                FROM products
                WHERE item_name IN ({placeholders})
                  AND COALESCE(status, '') != 'deleted'
                GROUP BY item_name, COALESCE(department, '')
            """, item_names).fetchall()
            for r in s_rows:
                key = (r["item_name"], r["department"])
                stock_map[key] = r

        items = []
        for pi in page_items:
            key = (pi["item_name"], pi["department"])
            s = stock_map.get(key) or {}
            items.append({
                "name": pi["item_name"],
                "department": pi["department"],
                "unit": pi["unit"] or "pcs",
                "stock": float(s.get("stock_qty") or 0),
                "avgBuyRate": float(s.get("avg_buy_rate") or 0),
                "stockValue": float(s.get("stock_value") or 0),
            })

    return jsonify({
        "items": items,
        "total": total_items,
        "totalValue": total_value,
        "page": page,
        "limit": limit,
    })


def _barcode_dict(bc):
    """Shape a purchase_item (+ optional joined party_name) row into the
    flat structure every frontend caller (scanner.js, replace.js) expects
    under a `barcode` key."""
    return {
        "code": str(bc.get("barcode_no") or ""),
        # "purchase_item_id" is actually the aggregate product_id — the
        # frontend uses it to group repeat scans of the same item+size
        # batch, and to ask /api/barcode_by_item for "another one like this".
        "purchase_item_id": bc.get("product_id"),
        "item": bc.get("item_name"),
        "size": bc.get("size"),
        "party": bc.get("party_name"),
        "sell_unit": float(bc["sale_price"]) if bc.get("sale_price") is not None else 0,
        "buy_unit": float(bc["buy_price"]) if bc.get("buy_price") is not None else 0,
        "margin": bc.get("margin"),
        "status": bc.get("is_available"),
        "sold_at": bc.get("sold_at"),
        "id": bc.get("id"),
        "invoiceNo": bc.get("invoice_no"),
        "invoiceDate": bc.get("invoice_date"),
        "remaining": float(bc.get("remaining") or 0),
    }


_BARCODE_SELECT = """
    SELECT pi.*, pt.party_name, ph.invoice_no, ph.date AS invoice_date, pr.remaining AS remaining
    FROM purchase_item pi
    LEFT JOIN parties pt ON pt.party_id = pi.party_id
    LEFT JOIN products pr ON pr.product_id = pi.product_id
    LEFT JOIN purchases_header ph ON ph.id = pr.purchase_id
"""


_BIGINT_MAX = 9223372036854775807


@items_bp.route("/api/barcode_lookup", methods=["GET"])
def barcode_lookup():
    code = (request.args.get("code") or "").strip()
    if not code:
        return jsonify({"status": "not_found", "message": "Code required."}), 400

    # If the input contains any non-numeric character → skip purchase_item and
    # old_data.barcode entirely and go straight to old_data.item_code search.
    is_pure_numeric = code.lstrip('-').isdigit()

    code_int = None
    if is_pure_numeric:
        try:
            code_int = int(code)
        except ValueError:
            is_pure_numeric = False

    if is_pure_numeric and code_int is not None and abs(code_int) > _BIGINT_MAX:
        return jsonify({"status": "not_found", "message": "Barcode not found."}), 404

    with get_conn() as conn:
        # ── Purely numeric input: try regular stock barcode first ────────────
        bc = None
        if is_pure_numeric and code_int is not None:
            bc = conn.execute(
                _BARCODE_SELECT + " WHERE pi.barcode_no=? AND pi.product_id IS NOT NULL LIMIT 1",
                (code_int,)
            ).fetchone()

        if not bc:
            if not is_pure_numeric:
                # Non-numeric input: go straight to old_data.item_code
                old_rows = conn.execute(
                    """
                    SELECT * FROM old_data
                    WHERE LOWER(TRIM(item_code)) = LOWER(TRIM(?))
                    ORDER BY (remaining > 0) DESC, id ASC
                    """,
                    (code,)
                ).fetchall()
            elif code_int is not None:
                # Pure numeric: ONLY check old_data.barcode — no item_code fallback
                old_rows = conn.execute(
                    """
                    SELECT * FROM old_data
                    WHERE barcode = ?
                    ORDER BY (remaining > 0) DESC, id ASC
                    """,
                    (code_int,)
                ).fetchall()
            else:
                old_rows = []

            if old_rows:
                distinct_sell_prices = {float(r["sell_mrp"] or 0) for r in old_rows}
                distinct_buy_prices = {float(r["buy_mrp"] or 0) for r in old_rows}
                has_different_prices = len(distinct_sell_prices) > 1 or len(distinct_buy_prices) > 1

                matches = [
                    {
                        "id": r["id"],
                        "uniqee_id": r["uniqee_id"] if "uniqee_id" in r else r.get("uniqee_id"),
                        "barcode": r.get("barcode"),
                        "code": r["item_code"],
                        "purchase_item_id": r["id"],
                        "item": r["item_code"],
                        "size": r.get("size") or "",
                        "party": "Old Stock",
                        "sell_unit": float(r["sell_mrp"] or 0),
                        "buy_unit": float(r["buy_mrp"] or 0),
                        "margin": 0,
                        "status": "available",
                        "sold_at": None,
                        "is_old_data": True,
                        "remaining": float(r["remaining"] or 0),
                        "sold": float(r["sold"] or 0),
                    }
                    for r in old_rows
                ]

                if has_different_prices:
                    return jsonify({
                        "status": "multiple_prices",
                        "has_different_prices": True,
                        "requires_selection": True,
                        "matches_count": len(old_rows),
                        "matches": matches,
                        "all_matches": matches,
                        "barcode": matches[0],
                        "message": f"Multiple records found in Old Stock for '{code}' with different prices. Please select an item."
                    })

                return jsonify({
                    "status": "ok",
                    "has_different_prices": False,
                    "matches_count": len(old_rows),
                    "barcode": matches[0]
                })

            return jsonify({"status": "not_found", "message": "Barcode not found."}), 404
        if bc["is_available"] == "deleted":
            return jsonify({
                "status": "deleted",
                "message": "This item has been deleted.",
                "barcode": _barcode_dict(dict(bc))
            }), 409
        if bc.get("is_returned"):
            return jsonify({
                "status": "already_sold",
                "message": "This item has been returned to vendor.",
                "barcode": _barcode_dict(dict(bc))
            }), 409
        return jsonify({"status": "ok", "barcode": _barcode_dict(dict(bc))})


_SOLD_BARCODE_SELECT = """
    SELECT pi.*, pt.party_name, ph.invoice_no, ph.date AS invoice_date,
           (
             SELECT si.unit_sale_price
             FROM sold_item_barcodes sib
             JOIN sold_items si ON si.sold_item_id = sib.sold_item_id
             WHERE sib.barcode_no = pi.barcode_no
             ORDER BY si.sold_item_id DESC
             LIMIT 1
           ) AS actual_sale_price
    FROM purchase_item pi
    LEFT JOIN parties pt ON pt.party_id = pi.party_id
    LEFT JOIN products pr ON pr.product_id = pi.product_id
    LEFT JOIN purchases_header ph ON ph.id = pr.purchase_id
"""


@items_bp.route("/api/barcode_lookup_sold", methods=["GET"])
def barcode_lookup_sold():
    code = (request.args.get("code") or "").strip()

    # Pure-numeric check: non-numeric input skips purchase_item + old_data.barcode
    is_pure_numeric = code.lstrip('-').isdigit() if code else False
    try:
        code_int = int(code) if is_pure_numeric else None
    except (TypeError, ValueError):
        code_int = None
        is_pure_numeric = False

    with get_conn() as conn:
        bc = None
        if is_pure_numeric and code_int is not None:
            bc = conn.execute(
                _SOLD_BARCODE_SELECT + """
                    WHERE pi.barcode_no=? AND pi.product_id IS NOT NULL
                    LIMIT 1
                """,
                (code_int,)
            ).fetchone()
        if not bc:
            od_si = None
            if is_pure_numeric and code_int is not None:
                # Numeric input: check old_data.barcode column only
                od_si = conn.execute("""
                    SELECT si.*, od.uniqee_id, od.barcode, od.item_code
                    FROM sold_items si
                    LEFT JOIN old_data od ON (od.id = si.product_id OR od.uniqee_id = si.product_id)
                    WHERE si.is_old = 1 AND od.barcode = ?
                    ORDER BY si.sold_item_id DESC
                    LIMIT 1
                """, (code_int,)).fetchone()
            elif code:
                # Non-numeric input: check item_code directly
                od_si = conn.execute("""
                    SELECT si.*, od.uniqee_id, od.barcode, od.item_code
                    FROM sold_items si
                    LEFT JOIN old_data od ON (od.uniqee_id = si.product_id OR od.id = si.product_id)
                    WHERE si.is_old = 1 AND (LOWER(TRIM(od.item_code)) = LOWER(TRIM(?)) OR LOWER(TRIM(si.item_name)) = LOWER(TRIM(?)))
                    ORDER BY si.sold_item_id DESC
                    LIMIT 1
                """, (code, code)).fetchone()

            if od_si and float(od_si["return_qty"] or 0) < float(od_si["quantity"] or 0):
                return jsonify({
                    "status": "ok",
                    "barcode": {
                        "code": str(od_si["product_id"] or od_si["uniqee_id"] or od_si["item_code"]),
                        "purchase_item_id": od_si["product_id"] or od_si["uniqee_id"],
                        "item": od_si["item_name"],
                        "size": od_si["size"] or "",
                        "party": "Old Stock",
                        "sell_unit": float(od_si["unit_sale_price"] or 0),
                        "buy_unit": float(od_si["unit_buy_price"] or 0),
                        "is_old_data": True,
                        "sold_item_id": od_si["sold_item_id"]
                    }
                })

            # od_exists: only for numeric (barcode match) or non-numeric (item_code match)
            od_exists = None
            if is_pure_numeric and code_int is not None:
                od_exists = conn.execute("SELECT * FROM old_data WHERE barcode = ? LIMIT 1", (code_int,)).fetchone()
            elif code:
                od_exists = conn.execute("SELECT * FROM old_data WHERE LOWER(TRIM(item_code)) = LOWER(TRIM(?)) ORDER BY id ASC LIMIT 1", (code,)).fetchone()
            if od_exists:
                return jsonify({
                    "status": "ok",
                    "barcode": {
                        "code": str(od_exists["uniqee_id"] or od_exists["id"] or od_exists["item_code"]),
                        "purchase_item_id": od_exists["uniqee_id"] or od_exists["id"],
                        "item": od_exists["item_code"],
                        "size": "",
                        "party": "Old Stock",
                        "sell_unit": float(od_exists["sell_mrp"] or 0),
                        "buy_unit": float(od_exists["buy_mrp"] or 0),
                        "is_old_data": True,
                        "sold_item_id": None
                    }
                })
            return jsonify({"status": "not_found", "message": "Barcode not found."}), 404
        if bc["is_available"] == "deleted":
            return jsonify({
                "status": "deleted",
                "message": "This item has been deleted.",
                "barcode": _barcode_dict(dict(bc))
            }), 409
        elif bc["is_available"] != "sold":
            return jsonify({
                "status": "not_sold",
                "message": "This barcode is not sold. Only sold barcodes can be returned."
            }), 409
        result = _barcode_dict(dict(bc))
        # Prefer the price the item was actually sold for (sold_items.unit_sale_price),
        # not the catalog sale_price stored on purchase_item at purchase time.
        actual = bc.get("actual_sale_price")
        if actual is not None:
            result["sell_unit"] = float(actual)
        return jsonify({"status": "ok", "barcode": result})


@items_bp.route("/api/product_search", methods=["GET"])
def product_search():
    q = (request.args.get("query") or "").strip()
    status = request.args.get("status") or "available"
    allow_barcode = request.args.get("allow_barcode", "1") not in ("0", "false", "False")
    if not q:
        return jsonify({"status": "ok", "matches": []})

    matches = []
    seen_product_ids = set()

    with get_conn() as conn:
        # 1. Exact barcode check if q is numeric and barcode search is allowed
        if allow_barcode and q.isdigit():
            try:
                code_int = int(q)
                rows = conn.execute("""
                    SELECT pi.id, pi.product_id, pi.item_name, pi.size, pi.barcode_no,
                           pi.buy_price, pi.sale_price, pi.margin, pi.is_available, pi.sold_at,
                           pt.party_name, NULL AS invoice_no, NULL AS invoice_date
                    FROM purchase_item pi
                    LEFT JOIN parties pt ON pt.party_id = pi.party_id
                    WHERE pi.barcode_no = ? AND pi.product_id IS NOT NULL AND pi.is_available = ?
                    LIMIT 5
                """, (code_int, status)).fetchall()
                for r in rows:
                    dict_r = dict(r)
                    matches.append(_barcode_dict(dict_r))
                    if dict_r.get("product_id"):
                        seen_product_ids.add(dict_r["product_id"])
            except (ValueError, TypeError):
                pass

        # 2. Fast Product Search from products table
        stock_clause = "p.status != 'deleted'" if status == "available" else "p.sold > 0"

        # Strategy A: Fast prefix / word-start search (~4ms to 40ms)
        prefix_rows = conn.execute(f"""
            SELECT p.product_id, p.item_name, p.size, pt.party_name,
                   p.unit_price AS buy_price, p.margin,
                   ROUND(p.unit_price * (1.0 + COALESCE(p.margin, 0) / 100.0), 2) AS sale_price
            FROM products p
            LEFT JOIN parties pt ON pt.party_id = p.party_id
            WHERE (p.item_name ILIKE ? OR p.item_name ILIKE ?) AND {stock_clause}
            LIMIT 30
        """, (f"{q}%", f"% {q}%")).fetchall()

        for r in prefix_rows:
            pid = r["product_id"]
            if pid not in seen_product_ids:
                seen_product_ids.add(pid)
                matches.append({
                    "barcode": "",
                    "purchase_item_id": pid,
                    "item": r["item_name"],
                    "size": r["size"],
                    "party": r["party_name"],
                    "sell_unit": float(r["sale_price"]) if r.get("sale_price") is not None else 0,
                    "buy_unit": float(r["buy_price"]) if r.get("buy_price") is not None else 0,
                    "margin": float(r["margin"]) if r.get("margin") is not None else 0,
                    "status": status,
                    "sold_at": None,
                    "id": None,
                    "invoiceNo": None,
                    "invoiceDate": None,
                })
                if len(matches) >= 30:
                    break

        # Strategy B: Substring search ONLY when query has >= 3 chars (for trigram index support)
        if len(matches) < 30 and len(q) >= 3:
            sub_rows = conn.execute(f"""
                SELECT p.product_id, p.item_name, p.size, pt.party_name,
                       p.unit_price AS buy_price, p.margin,
                       ROUND(p.unit_price * (1.0 + COALESCE(p.margin, 0) / 100.0), 2) AS sale_price
                FROM products p
                LEFT JOIN parties pt ON pt.party_id = p.party_id
                WHERE p.item_name ILIKE ? AND {stock_clause}
                LIMIT 30
            """, (f"%{q}%",)).fetchall()

            for r in sub_rows:
                pid = r["product_id"]
                if pid not in seen_product_ids:
                    seen_product_ids.add(pid)
                    matches.append({
                        "barcode": "",
                        "purchase_item_id": pid,
                        "item": r["item_name"],
                        "size": r["size"],
                        "party": r["party_name"],
                        "sell_unit": float(r["sale_price"]) if r.get("sale_price") is not None else 0,
                        "buy_unit": float(r["buy_price"]) if r.get("buy_price") is not None else 0,
                        "margin": float(r["margin"]) if r.get("margin") is not None else 0,
                        "status": status,
                        "sold_at": None,
                        "id": None,
                        "invoiceNo": None,
                        "invoiceDate": None,
                    })
                    if len(matches) >= 30:
                        break

    return jsonify({"status": "ok", "matches": matches[:30]})



@items_bp.route("/api/barcode_by_item", methods=["GET"])
def barcode_by_item():
    product_id = request.args.get("purchase_item_id")
    status = request.args.get("status") or "available"
    exclude_codes = [c.strip() for c in (request.args.get("exclude") or "").split(",") if c.strip()]

    if not product_id:
        return jsonify({"status": "not_found", "message": "purchase_item_id required."}), 400
    try:
        product_id = int(product_id)
    except ValueError:
        return jsonify({"status": "not_found", "message": "Invalid purchase_item_id."}), 400

    sql = _BARCODE_SELECT + " WHERE pi.product_id=? AND pi.is_available=?"
    params = [product_id, status]
    if exclude_codes:
        placeholders = ",".join("?" for _ in exclude_codes)
        sql += f" AND CAST(pi.barcode_no AS TEXT) NOT IN ({placeholders})"
        params.extend(exclude_codes)
    sql += " ORDER BY pi.id LIMIT 1"

    with get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
        if not row and status == "available":
            # Fallback for remaining <= 0: pick any barcode of this product so it can be sold
            fallback_sql = _BARCODE_SELECT + " WHERE pi.product_id=? ORDER BY pi.id DESC LIMIT 1"
            row = conn.execute(fallback_sql, (product_id,)).fetchone()
        if not row:
            return jsonify({"status": "not_found", "message": "No more matching units found."}), 404
        result = _barcode_dict(dict(row))
        # When picking a sold unit (e.g. replace old side), use actual sold price.
        if status == "sold" and row.get("barcode_no") is not None:
            sold_row = conn.execute("""
                SELECT si.unit_sale_price
                FROM sold_item_barcodes sib
                JOIN sold_items si ON si.sold_item_id = sib.sold_item_id
                WHERE sib.barcode_no = ?
                ORDER BY si.sold_item_id DESC
                LIMIT 1
            """, (row["barcode_no"],)).fetchone()
            if sold_row and sold_row["unit_sale_price"] is not None:
                result["sell_unit"] = float(sold_row["unit_sale_price"])
        return jsonify({"status": "ok", "barcode": result})


@items_bp.route("/api/used_codes", methods=["GET"])
def get_used_codes():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT barcode_no AS code FROM purchase_item
            WHERE is_available='sold' AND product_id IS NOT NULL
        """).fetchall()
    return jsonify([str(r["code"]) for r in rows])


@items_bp.route("/api/sell_scanned", methods=["POST"])
def sell_scanned():
    data = request.json or {}
    codes = data.get("codes") or []
    if isinstance(codes, str):
        codes = [codes]
    sold = []
    for c in codes:
        if mark_barcode_sold(c):
            sold.append(c)
    if sold:
        import core.dashboard_cache as dashboard_cache
        with get_conn() as conn:
            dashboard_cache.recompute_global_snapshot(conn)
    return jsonify({"status": "ok", "sold": sold})


@items_bp.route("/api/barcodes/purchase/<int:purchase_item_id>", methods=["GET"])
def get_barcodes_by_purchase_item(purchase_item_id):
    """purchase_item_id here is product_id (aggregate line)."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT barcode_no AS code, is_available AS status
            FROM purchase_item
            WHERE product_id=? ORDER BY id
        """, (purchase_item_id,)).fetchall()
    return jsonify([{"code": str(r["code"]), "status": r["status"]} for r in rows])


@items_bp.route("/api/barcodes/by_purchase/<int:purchase_id>", methods=["GET"])
def get_barcodes_by_purchase(purchase_id):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT pr.product_id, pr.item_name, pr.size, pr.unit_price,
                   pi.barcode_no, pi.is_available, pi.sale_price
            FROM products pr
            JOIN purchase_item pi ON pi.product_id = pr.product_id
            WHERE pr.purchase_id = ?
            ORDER BY pr.product_id, pi.id
        """, (purchase_id,)).fetchall()
        groups = {}
        for r in rows:
            pid = r["product_id"]
            if pid not in groups:
                groups[pid] = {
                    "purchase_item_id": pid,
                    "item": r["item_name"],
                    "size": r["size"],
                    "sell_price": r["sale_price"] or r["unit_price"],
                    "barcodes": []
                }
            groups[pid]["barcodes"].append({
                "code": str(r["barcode_no"]),
                "status": r["is_available"]
            })
    return jsonify(list(groups.values()))


@items_bp.route("/api/barcodes/pdf", methods=["POST"])
def barcodes_pdf():
    """Builds an A4 sheet of barcode labels as a PDF (offline, via ReportLab).
    Default layout is 4 columns x 12 rows = 48 labels per page."""
    from flask import Response
    from core import barcode_pdf

    data = request.json or {}
    labels = [l for l in (data.get("labels") or []) if str(l.get("code") or "").strip()]
    if not labels:
        return jsonify({"status": "error", "message": "No barcodes to print"}), 400
    if len(labels) > 5000:
        return jsonify({"status": "error", "message": "Too many barcodes in one go (max 5000)"}), 400

    def num(key, default=None):
        v = data.get(key)
        try:
            return default if v in (None, "") else float(v)
        except (TypeError, ValueError):
            return default

    cols = int(num("cols", 4))
    rows = int(num("rows", 12))
    if not (1 <= cols <= 10 and 1 <= rows <= 30):
        return jsonify({"status": "error", "message": "Columns must be 1-10 and rows 1-30"}), 400
    try:
        pdf = barcode_pdf.build_barcode_pdf(
            labels, cols=cols, rows=rows,
            label_w=num("label_w"), label_h=num("label_h"),
            margin_left=num("margin_left"), margin_top=num("margin_top"),
            gap_x=num("gap_x", 0.0), gap_y=num("gap_y", 0.0),
            border=data.get("border", True) is not False,
            show_name=data.get("show_name", True) is not False,
            show_size=data.get("show_size", True) is not False,
            show_price=data.get("show_price", True) is not False,
        )
    except ImportError:
        return jsonify({"status": "error", "message": "reportlab is not installed. Run: pip install reportlab"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": "Could not build barcode PDF: " + str(e)}), 500
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": "inline; filename=barcodes.pdf"})


@items_bp.route("/api/barcodes/next", methods=["GET"])
def get_next_barcode():
    with get_conn() as conn:
        result = conn.execute(
            "SELECT last_barcode AS last_number FROM purchase_item WHERE barcode_no = 0"
        ).fetchone()
        next_num = (result["last_number"] if result else 9999) + 1
    return jsonify({"next": next_num, "code": str(next_num).zfill(5)})


# ─── OLD DATA LOOKUP & FETCH ────────────────────────────────────────────────
# Lookup an item from the legacy `old_data` table (imported from xlsx).
# Called when the barcode field contains letters (A-Z) — routed by scanner.js.
# Returns the same barcode-dict shape as /api/barcode_lookup so the frontend
# can add it to the cart identically, with an extra `is_old_data: true` flag.

@items_bp.route("/api/old_data_lookup", methods=["GET"])
def old_data_lookup():
    code = (request.args.get("code") or "").strip()
    data_id = request.args.get("id")
    if not code and not data_id:
        return jsonify({"status": "not_found", "message": "Item code or ID required."}), 400

    with get_conn() as conn:
        if data_id:
            try:
                row = conn.execute(
                    "SELECT * FROM old_data WHERE id = ?",
                    (int(data_id),)
                ).fetchone()
                rows = [row] if row else []
            except (ValueError, TypeError):
                rows = []
                row = None
        else:
            # When duplicate item codes exist, prioritize rows with remaining stock > 0, then id ASC
            code_num = None
            try:
                code_num = int(code)
            except (ValueError, TypeError):
                pass

            is_pure_numeric = code.lstrip('-').isdigit() if code else False

            if is_pure_numeric and code_num is not None:
                # Numeric input: ONLY check old_data.barcode — no item_code fallback
                rows = conn.execute(
                    """
                    SELECT * FROM old_data
                    WHERE barcode = ?
                    ORDER BY (remaining > 0) DESC, id ASC
                    """,
                    (code_num,)
                ).fetchall()
            else:
                # Non-numeric input: go straight to item_code search
                rows = conn.execute(
                    """
                    SELECT * FROM old_data
                    WHERE LOWER(TRIM(item_code)) = LOWER(TRIM(?))
                    ORDER BY (remaining > 0) DESC, id ASC
                    """,
                    (code,)
                ).fetchall()
            row = rows[0] if rows else None

        if not row:
            return jsonify({
                "status": "not_found",
                "message": f"Old Stock item '{code or data_id}' not found."
            }), 404

        matches = [
            {
                "id": r["id"],
                "uniqee_id": r["uniqee_id"] if "uniqee_id" in r else r.get("uniqee_id"),
                "barcode": r.get("barcode"),
                "code": r["item_code"],
                "purchase_item_id": r["id"],      # old_data.id — used as group key in cart
                "item": r["item_code"],
                "size": r.get("size") or "",
                "party": "Old Stock",
                "sell_unit": float(r["sell_mrp"] or 0),
                "buy_unit": float(r["buy_mrp"] or 0),
                "margin": 0,
                "status": "available",
                "sold_at": None,
                "invoiceNo": None,
                "invoiceDate": None,
                "is_old_data": True,
                "remaining": float(r["remaining"] or 0),
                "sold": float(r["sold"] or 0),
            }
            for r in rows
        ]

        # When searching by code (not explicit id) and duplicate rows exist:
        # Check if rows differ by price OR by size — either requires the user to
        # pick explicitly so we never silently sell the wrong size / wrong price.
        if not data_id and len(rows) > 1:
            distinct_sell_prices = {float(r["sell_mrp"] or 0) for r in rows}
            distinct_buy_prices  = {float(r["buy_mrp"]  or 0) for r in rows}
            distinct_sizes       = {(r.get("size") or "").strip() for r in rows}
            has_different_prices = len(distinct_sell_prices) > 1 or len(distinct_buy_prices) > 1
            has_different_sizes  = len(distinct_sizes) > 1

            if has_different_prices or has_different_sizes:
                if has_different_prices and has_different_sizes:
                    reason_msg = "different sizes and prices"
                elif has_different_sizes:
                    reason_msg = "different sizes"
                else:
                    reason_msg = "different prices"
                return jsonify({
                    "status": "multiple_prices",          # kept for backward-compat
                    "has_different_prices": has_different_prices,
                    "has_different_sizes": has_different_sizes,
                    "requires_selection": True,
                    "matches_count": len(rows),
                    "matches": matches,
                    "all_matches": matches,
                    "barcode": matches[0],
                    "message": f"Multiple records found for '{code}' with {reason_msg}. Please select which item to sell."
                })

        return jsonify({
            "status": "ok",
            "has_different_prices": False,
            "has_different_sizes": False,
            "matches_count": len(rows),
            "barcode": matches[0]
        })


@items_bp.route("/api/old_data", methods=["GET"])
def api_get_old_data():
    """Fetch rows from old_data table exactly as xlsx (supporting search and pagination)."""
    try:
        page = max(int(request.args.get("page") or 1), 1)
    except (TypeError, ValueError):
        page = 1
    try:
        limit = max(min(int(request.args.get("limit") or 100), 10000), 1)
    except (TypeError, ValueError):
        limit = 100
    search = (request.args.get("search") or "").strip()
    offset = (page - 1) * limit

    with get_conn() as conn:
        if search:
            total = conn.execute(
                "SELECT COUNT(*) AS cnt FROM old_data WHERE item_code ILIKE ? OR CAST(uniqee_id AS TEXT) ILIKE ? OR CAST(barcode AS TEXT) ILIKE ?",
                (f"%{search}%", f"%{search}%", f"%{search}%")
            ).fetchone()["cnt"]
            rows = conn.execute(
                "SELECT * FROM old_data WHERE item_code ILIKE ? OR CAST(uniqee_id AS TEXT) ILIKE ? OR CAST(barcode AS TEXT) ILIKE ? ORDER BY id ASC LIMIT ? OFFSET ?",
                (f"%{search}%", f"%{search}%", f"%{search}%", limit, offset)
            ).fetchall()
        else:
            total = conn.execute("SELECT COUNT(*) AS cnt FROM old_data").fetchone()["cnt"]
            rows = conn.execute(
                "SELECT * FROM old_data ORDER BY id ASC LIMIT ? OFFSET ?",
                (limit, offset)
            ).fetchall()

        # Totals across ALL matching rows (not just this page) for the Items / Stock tabs
        if search:
            agg = conn.execute(
                "SELECT COALESCE(SUM(remaining), 0) AS qty, "
                "COALESCE(SUM(remaining * buy_mrp), 0) AS val, "
                "COALESCE(SUM(remaining * (sell_mrp - buy_mrp)), 0) AS margin "
                "FROM old_data WHERE item_code ILIKE ? OR CAST(uniqee_id AS TEXT) ILIKE ? OR CAST(barcode AS TEXT) ILIKE ?",
                (f"%{search}%", f"%{search}%", f"%{search}%")
            ).fetchone()
        else:
            agg = conn.execute(
                "SELECT COALESCE(SUM(remaining), 0) AS qty, "
                "COALESCE(SUM(remaining * buy_mrp), 0) AS val, "
                "COALESCE(SUM(remaining * (sell_mrp - buy_mrp)), 0) AS margin "
                "FROM old_data"
            ).fetchone()

        items = [
            {
                "id": r["id"],
                "uniqee_id": r.get("uniqee_id"),
                "barcode": r.get("barcode"),
                "item_code": r["item_code"],
                "size": r.get("size") or "",
                "buy_mrp": float(r["buy_mrp"]),
                "sell_mrp": float(r["sell_mrp"]),
                "remaining": float(r["remaining"]),
                "sold": float(r["sold"]),
                "is_return": int(r.get("is_return", 0) or 0),
                "imported_at": str(r["imported_at"]) if r["imported_at"] else None
            }
            for r in rows
        ]

        return jsonify({
            "status": "ok",
            "total": total,
            "page": page,
            "limit": limit,
            "total_qty": float(agg["qty"]),
            "total_value": float(agg["val"]),
            "total_margin": float(agg["margin"]),
            "items": items
        })


@items_bp.route("/api/old_data/reimport", methods=["POST"])
def api_reimport_old_data():
    """Trigger a clean re-import of Old_Data/old_purchase_data.xlsx accepting duplicates."""
    from core.schema import import_old_data_if_needed
    try:
        import_old_data_if_needed(force=True)
        return jsonify({"status": "ok", "message": "Old data re-imported successfully from xlsx."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

