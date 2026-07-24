import sqlite3

from flask import Blueprint, request, jsonify

from core.db import get_conn

parties_bp = Blueprint("parties", __name__)

def load_parties():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM parties ORDER BY name").fetchall()
    return [dict(r) for r in rows]

def add_party(name, seller_no, address, gst_no):
    with get_conn() as conn:
        try:
            conn.execute("INSERT INTO parties(name,seller_no,address,gst_no) VALUES(?,?,?,?)",
                         (name, seller_no, address, gst_no))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

def delete_party(name):
    with get_conn() as conn:
        c = conn.execute("DELETE FROM parties WHERE name=?", (name,))
        conn.commit()
    return c.rowcount > 0

@parties_bp.route("/api/parties", methods=["GET"])
def get_parties():
    return jsonify(load_parties())

@parties_bp.route("/api/parties", methods=["POST"])
def api_add_party():
    data = request.json or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"status": "invalid", "message": "Name required"}), 400
    ok = add_party(name, data.get("sellerNo",""), data.get("address",""), data.get("gstNo",""))
    if not ok:
        return jsonify({"status": "exists", "message": "Party already exists"}), 409
    return jsonify({"status": "ok", "parties": load_parties()})

@parties_bp.route("/api/parties/<path:name>", methods=["DELETE"])
def api_delete_party(name):
    ok = delete_party(name)
    if not ok:
        return jsonify({"status": "not_found"}), 404
    return jsonify({"status": "ok", "parties": load_parties()})
