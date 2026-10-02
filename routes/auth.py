from flask import Blueprint, request, jsonify, session

from core.db import get_conn
from core.auth import hash_password, verify_password

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/api/auth/status", methods=["GET"])
def auth_status():
    """Tells the frontend whether to show the first-run setup form, the
    login form, or nothing (already logged in)."""
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM manage_user").fetchone()["c"]

    if total == 0:
        return jsonify({"setup_required": True, "logged_in": False})

    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"setup_required": False, "logged_in": False})

    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, user_name AS username, role, is_active FROM manage_user WHERE id=?",
            (user_id,)
        ).fetchone()

    if not row or not row["is_active"]:
        session.clear()
        return jsonify({"setup_required": False, "logged_in": False})

    return jsonify({
        "setup_required": False,
        "logged_in": True,
        "user": {"id": row["id"], "username": row["username"], "role": row["role"]}
    })


@auth_bp.route("/api/auth/setup", methods=["POST"])
def auth_setup():
    """Creates the very first admin account. Only works while the
    manage_user table is empty, so the app can never be left in a
    permanently-locked-out state, and no hardcoded credentials are needed."""
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM manage_user").fetchone()["c"]
        if total > 0:
            return jsonify({"error": "Setup already completed. Please log in."}), 400
        cur = conn.execute("""
            INSERT INTO manage_user (user_name, password, role, is_active, created_at, updated_at)
            VALUES (?, ?, 'admin', TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, (username, hash_password(password)))
        user_id = cur.lastrowid

    session.clear()
    session["user_id"] = user_id
    return jsonify({"status": "ok", "user": {"id": user_id, "username": username, "role": "admin"}})


@auth_bp.route("/api/auth/login", methods=["POST"])
def auth_login():
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400

    with get_conn() as conn:
        row = conn.execute("SELECT id, user_name AS username, password AS password_hash, role, is_active FROM manage_user WHERE user_name=?", (username,)).fetchone()

    if not row or not verify_password(password, row["password_hash"]):
        return jsonify({"error": "Invalid username or password"}), 401

    if not row["is_active"]:
        return jsonify({"error": "This account is inactive. Contact your administrator."}), 403

    session.clear()
    session["user_id"] = row["id"]
    return jsonify({
        "status": "ok",
        "user": {"id": row["id"], "username": row["username"], "role": row["role"]}
    })


@auth_bp.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    session.clear()
    return jsonify({"status": "ok"})