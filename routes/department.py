import sqlite3

from flask import Blueprint, request, jsonify

from core.db import get_conn

department_bp = Blueprint("department", __name__)

def load_departments():
    with get_conn() as conn:
        rows = conn.execute("SELECT name FROM departments ORDER BY name").fetchall()
    return [r["name"] for r in rows]

def add_department(name):
    with get_conn() as conn:
        try:
            conn.execute("INSERT INTO departments(name) VALUES(?)", (name,))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

def delete_department(name):
    with get_conn() as conn:
        c = conn.execute("DELETE FROM departments WHERE name=?", (name,))
        conn.commit()
    return c.rowcount > 0

@department_bp.route("/api/departments", methods=["GET"])
def get_departments():
    return jsonify(load_departments())

@department_bp.route("/api/departments", methods=["POST"])
def api_add_department():
    data = request.json or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"status": "invalid", "message": "Name required"}), 400
    ok = add_department(name)
    if not ok:
        return jsonify({"status": "exists", "message": "Department already exists"}), 409
    return jsonify({"status": "ok", "departments": load_departments()})

@department_bp.route("/api/departments/<path:name>", methods=["DELETE"])
def api_delete_department(name):
    ok = delete_department(name)
    if not ok:
        return jsonify({"status": "not_found"}), 404
    return jsonify({"status": "ok", "departments": load_departments()})
