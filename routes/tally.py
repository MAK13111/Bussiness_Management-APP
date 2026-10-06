import psycopg2

from flask import Blueprint, request, jsonify

from core.db import get_conn
from core.accounting import VoucherEngine

tally_bp = Blueprint("tally", __name__)

@tally_bp.route("/api/tally/account_groups", methods=["GET"])
def get_account_groups():
    with get_conn() as conn:
        groups = conn.execute("SELECT * FROM account_groups ORDER BY name").fetchall()
    return jsonify([dict(g) for g in groups])

@tally_bp.route("/api/tally/ledgers", methods=["GET"])
def get_ledgers():
    # page-based pagination (used by the "Manage Ledgers" list UI, same
    # convention as /api/vouchers, /api/items, /api/reports/*): when `page`
    # is passed, response is wrapped as {entries,total,page,limit} so the
    # frontend can render a Prev/Next + "Page X of Y" bar. Without `page`
    # (e.g. dropdowns/datalists that need every ledger), behaviour is
    # unchanged -- the full array is returned.
    page = request.args.get("page", type=int)
    limit = request.args.get("limit", default=100, type=int)

    query = """
        SELECT l.*, g.name as group_name
        FROM ledgers l
        LEFT JOIN account_groups g ON g.id = l.group_id
        WHERE l.is_active = TRUE
        ORDER BY l.name
    """
    params = []
    if page and limit:
        offset = (page - 1) * limit
        query += " LIMIT ? OFFSET ?"
        params += [limit, offset]

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        if page and limit:
            total = conn.execute(
                "SELECT COUNT(*) as cnt FROM ledgers WHERE is_active = TRUE"
            ).fetchone()['cnt']
            return jsonify({'entries': [dict(r) for r in rows], 'total': total, 'page': page, 'limit': limit})

    return jsonify([dict(r) for r in rows])

@tally_bp.route("/api/tally/ledgers", methods=["POST"])
def create_ledger():
    data = request.json
    with get_conn() as conn:
        try:
            # group_id can be passed directly, or a group name (e.g. "Sundry Creditors") —
            # resolve group_id from name if group_id was not provided
            group_id = data.get('group_id')
            if not group_id and data.get('group'):
                grp = conn.execute("SELECT id FROM account_groups WHERE name=?", (data['group'],)).fetchone()
                if grp:
                    group_id = grp['id']

            cur = conn.execute("""
                INSERT INTO ledgers
                (name, group_id, opening_balance, balance_type, contact_person,
                 phone, email, address, gst_no, pan_no, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data['name'], group_id,
                data.get('opening_balance', 0), data.get('balance_type', 'Debit'),
                data.get('contact_person', ''), data.get('phone', ''),
                data.get('email', ''), data.get('address', ''),
                data.get('gst_no', ''), data.get('pan_no', ''), True
            ))
            conn.commit()
            return jsonify({"status": "ok", "id": cur.lastrowid})
        except psycopg2.IntegrityError:
            return jsonify({"error": "Ledger already exists"}), 409

@tally_bp.route("/api/tally/ledgers/<int:ledger_id>", methods=["PUT"])
def update_ledger(ledger_id):
    data = request.json
    with get_conn() as conn:
        conn.execute("""
            UPDATE ledgers
            SET name=?, group_id=?, opening_balance=?, balance_type=?,
                contact_person=?, phone=?, email=?, address=?, gst_no=?, pan_no=?, is_active=?
            WHERE id=?
        """, (
            data['name'], data.get('group_id'), data.get('opening_balance', 0),
            data.get('balance_type', 'Debit'), data.get('contact_person', ''),
            data.get('phone', ''), data.get('email', ''), data.get('address', ''),
            data.get('gst_no', ''), data.get('pan_no', ''), bool(data.get('is_active', True)),
            ledger_id
        ))
        conn.commit()
    return jsonify({"status": "ok"})

@tally_bp.route("/api/tally/ledgers/<int:ledger_id>", methods=["DELETE"])
def delete_ledger(ledger_id):
    with get_conn() as conn:
        used = conn.execute("SELECT 1 FROM voucher_entries WHERE ledger_id=? LIMIT 1", (ledger_id,)).fetchone()
        if used:
            return jsonify({"error": "Ledger used in vouchers"}), 400
        conn.execute("DELETE FROM ledgers WHERE id=?", (ledger_id,))
        conn.commit()
    return jsonify({"status": "ok"})

@tally_bp.route("/api/vouchers", methods=["GET"])
def get_vouchers():
    voucher_type = request.args.get("type")
    from_date = request.args.get("from")
    to_date = request.args.get("to")
    party = request.args.get("party")
    amount_min = request.args.get("amount_min", type=float)
    amount_max = request.args.get("amount_max", type=float)
    status = request.args.get("status")

    # page-based pagination: when `page` is passed, response is wrapped as
    # {entries,total,page,limit} so the frontend can render Prev/Next controls.
    page = request.args.get("page", type=int)

    # Default 200 per page; pass ?limit=0 to fetch everything (export).
    limit = request.args.get("limit", default=200, type=int)
    offset = request.args.get("offset", default=0, type=int)
    if page and limit:
        offset = (page - 1) * limit

    # Build the WHERE conditions shared by both the data and count queries.
    where_clause = "WHERE 1=1"
    params = []
    if voucher_type:
        where_clause += " AND vt.code = ?"
        params.append(voucher_type)
    if from_date:
        where_clause += " AND v.date >= ?"
        params.append(from_date)
    if to_date:
        where_clause += " AND v.date <= ?"
        params.append(to_date)
    if party:
        where_clause += " AND v.id IN (SELECT voucher_id FROM voucher_entries ve JOIN ledgers l ON l.id = ve.ledger_id WHERE l.name LIKE ?)"
        params.append(f"%{party}%")
    if status:
        where_clause += " AND v.is_posted = ?"
        params.append(status == 'posted')
    if amount_min is not None or amount_max is not None:
        where_clause += " AND v.id IN (SELECT voucher_id FROM voucher_entries GROUP BY voucher_id HAVING"
        if amount_min is not None:
            where_clause += " SUM(credit) >= ?"
            params.append(amount_min)
        if amount_max is not None:
            if amount_min is not None:
                where_clause += " AND"
            where_clause += " SUM(credit) <= ?"
            params.append(amount_max)
        where_clause += ")"

    with get_conn() as conn:
        # ── Step 1: paginate voucher IDs (fast – uses date + type indexes) ──
        id_params = list(params)
        id_query = f"""
            SELECT v.id, v.*, vt.code as voucher_type, vt.name as voucher_type_name
            FROM vouchers v
            JOIN voucher_types vt ON vt.id = v.voucher_type_id
            {where_clause}
            ORDER BY v.date DESC, v.id DESC
        """
        if limit and limit > 0:
            id_query += " LIMIT ? OFFSET ?"
            id_params += [limit, offset]
        rows = conn.execute(id_query, id_params).fetchall()

        if not rows:
            if page and limit:
                total_param = request.args.get("total", type=int) or request.args.get("known_total", type=int)
                total = total_param if (total_param is not None and total_param > 0) else 0
                return jsonify({'entries': [], 'total': total, 'page': page, 'limit': limit})
            return jsonify([])

        # ── Step 2: batch-fetch amounts + party names for this page only ──
        # This replaces 2 correlated subqueries per row with 2 single-pass lookups.
        voucher_ids = [r['id'] for r in rows]
        id_list = ",".join(str(i) for i in voucher_ids)

        amounts = {
            r['voucher_id']: r['amount']
            for r in conn.execute(f"""
                SELECT voucher_id,
                       GREATEST(COALESCE(SUM(debit),0), COALESCE(SUM(credit),0)) as amount
                FROM voucher_entries
                WHERE voucher_id IN ({id_list})
                GROUP BY voucher_id
            """).fetchall()
        }

        parties = {
            r['voucher_id']: r['party_name']
            for r in conn.execute(f"""
                SELECT DISTINCT ON (ve.voucher_id) ve.voucher_id, l.name as party_name
                FROM voucher_entries ve
                JOIN ledgers l        ON l.id  = ve.ledger_id
                JOIN account_groups ag ON ag.id = l.group_id
                WHERE ve.voucher_id IN ({id_list})
                  AND ag.name IN ('Sundry Debtors', 'Sundry Creditors')
                ORDER BY ve.voucher_id
            """).fetchall()
        }

        entries = []
        for r in rows:
            d = dict(r)
            d['amount']     = amounts.get(r['id'], 0)
            d['party_name'] = parties.get(r['id'])
            entries.append(d)

        if page and limit:
            total_param = request.args.get("total", type=int) or request.args.get("known_total", type=int)
            if total_param is not None and total_param > 0:
                total = total_param
            else:
                total = conn.execute(
                    f"SELECT COUNT(*) as cnt FROM vouchers v JOIN voucher_types vt ON vt.id = v.voucher_type_id {where_clause}",
                    params
                ).fetchone()['cnt']
            return jsonify({'entries': entries, 'total': total, 'page': page, 'limit': limit})

    return jsonify(entries)


@tally_bp.route("/api/vouchers", methods=["POST"])
def create_voucher():
    data = request.json


    try:
        result = VoucherEngine.create_voucher(data)
        return jsonify({"status": "ok", "voucher_id": result["voucher_id"], "voucher_number": result["voucher_number"]})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@tally_bp.route("/api/vouchers/<int:voucher_id>", methods=["GET"])
def get_voucher(voucher_id):
    voucher = VoucherEngine.get_voucher(voucher_id)
    if not voucher:
        return jsonify({"error": "Not found"}), 404
    return jsonify(voucher)

@tally_bp.route("/api/vouchers/<int:voucher_id>", methods=["PUT"])
def update_voucher(voucher_id):
    data = request.json
    try:
        result = VoucherEngine.update_voucher(voucher_id, data)
        return jsonify({"status": "ok", "voucher_id": result["voucher_id"], "voucher_number": result["voucher_number"]})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@tally_bp.route("/api/tally/trial_balance", methods=["GET"])
def get_trial_balance():
    date = request.args.get("as_on_date")
    result = VoucherEngine.get_trial_balance(date)
    return jsonify(result)

@tally_bp.route("/api/tally/balance_sheet", methods=["GET"])
def get_balance_sheet():
    date = request.args.get("as_on_date")
    result = VoucherEngine.get_balance_sheet(date)
    return jsonify(result)

@tally_bp.route("/api/tally/profit_loss", methods=["GET"])
def get_profit_loss():
    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")
    if not from_date or not to_date:
        return jsonify({"error": "from_date and to_date required"}), 400
    result = VoucherEngine.get_profit_loss(from_date, to_date)
    return jsonify(result)

@tally_bp.route("/api/tally/ledger_statement", methods=["GET"])
def get_ledger_statement():
    ledger_id_raw = request.args.get("ledger_id")
    from_date = request.args.get("from")
    to_date = request.args.get("to")
    if not ledger_id_raw:
        return jsonify({"error": "ledger_id required"}), 400
    ledger_id = None if ledger_id_raw == "all" else int(ledger_id_raw)

    # page-based pagination (same {entries,total,page,limit} convention as
    # /api/vouchers, /api/tally/ledgers, /api/items). Without `page`,
    # behaviour is unchanged -- the full array is returned.
    page = request.args.get("page", type=int)
    limit = request.args.get("limit", default=100, type=int)

    result = VoucherEngine.get_ledger_statement(ledger_id, from_date, to_date)

    if not page or not limit:
        return jsonify(result)

    # The running balance is order-dependent (and, in "all ledgers" mode,
    # resets whenever the ledger name changes), so pagination happens here
    # rather than in SQL: each page needs the balance carried in from every
    # row before it, plus which ledger that balance belongs to.
    total = len(result)
    offset = (page - 1) * limit

    opening_balance = 0.0
    opening_ledger = None
    for row in result[:offset]:
        if ledger_id is None and row['ledger_name'] != opening_ledger:
            opening_balance = 0.0
            opening_ledger = row['ledger_name']
        opening_balance += (row.get('debit') or 0) - (row.get('credit') or 0)

    return jsonify({
        'entries': result[offset:offset + limit],
        'total': total,
        'page': page,
        'limit': limit,
        'opening_balance': opening_balance,
        'opening_ledger': opening_ledger
    })

@tally_bp.route("/api/tally/day_book", methods=["GET"])
def get_day_book():
    date = request.args.get("date")
    if not date:
        return jsonify({"error": "date required"}), 400
    result = VoucherEngine.get_day_book(date)
    return jsonify(result)

@tally_bp.route("/api/accounts", methods=["GET"])
def get_accounts():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT l.id, l.name, g.name as type, l.opening_balance as "openingBalance",
                   (l.opening_balance + COALESCE(SUM(ve.debit) - SUM(ve.credit), 0)) as "currentBalance",
                   '' as "accountNo", '' as ifsc
            FROM ledgers l
            LEFT JOIN voucher_entries ve ON ve.ledger_id = l.id
            LEFT JOIN vouchers v ON v.id = ve.voucher_id
            JOIN account_groups g ON g.id = l.group_id
            WHERE g.name IN ('Cash-in-Hand', 'Bank Accounts') AND l.is_active = TRUE
            GROUP BY l.id, g.name
            ORDER BY l.name
        """).fetchall()
    return jsonify([dict(r) for r in rows])

@tally_bp.route("/api/accounts", methods=["POST"])
def add_account():
    data = request.json or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name required"}), 400
    account_type = data.get("type", "cash")
    opening_balance = float(data.get("openingBalance", 0))
    account_no = data.get("accountNo", "")

    group_name = "Cash-in-Hand" if account_type == "cash" else "Bank Accounts"
    with get_conn() as conn:
        group = conn.execute("SELECT id FROM account_groups WHERE name=?", (group_name,)).fetchone()
        if not group:
            return jsonify({"error": "Account group not found"}), 400
        group_id = group['id']
        existing = conn.execute("SELECT id FROM ledgers WHERE name=?", (name,)).fetchone()
        if existing:
            return jsonify({"error": "Ledger already exists"}), 409
        cur = conn.execute("""
            INSERT INTO ledgers (name, group_id, opening_balance, balance_type, is_active)
            VALUES (?, ?, ?, ?, ?)
        """, (name, group_id, opening_balance, "Debit", True))
        ledger_id = cur.lastrowid
        conn.execute("""
            INSERT INTO accounts (name, type, openingBalance, currentBalance, accountNo)
            VALUES (?, ?, ?, ?, ?)
        """, (name, account_type, opening_balance, opening_balance, account_no))
        conn.commit()
    return jsonify({"status": "ok", "id": ledger_id})

@tally_bp.route("/api/accounts/<path:name>", methods=["DELETE"])
def delete_account(name):
    with get_conn() as conn:
        ledger_row = conn.execute("SELECT id FROM ledgers WHERE name=?", (name,)).fetchone()
        if not ledger_row:
            return jsonify({"error": "Not found"}), 404
        used = conn.execute(
            "SELECT 1 FROM voucher_entries WHERE ledger_id=? LIMIT 1", (ledger_row["id"],)
        ).fetchone()
        if used:
            return jsonify({"error": "Ledger used in vouchers — cannot delete"}), 400
        c = conn.execute("DELETE FROM ledgers WHERE name=?", (name,))
        if c.rowcount == 0:
            return jsonify({"error": "Not found"}), 404
        conn.execute("DELETE FROM accounts WHERE name=?", (name,))
        conn.commit()
    return jsonify({"status": "ok"})
