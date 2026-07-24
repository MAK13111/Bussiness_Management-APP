import os
import io
import csv
import shutil
from datetime import datetime

from flask import Blueprint, request, jsonify, send_file, Response
from openpyxl import Workbook

from core.db import get_conn, MAIN_DB

setting_bp = Blueprint("setting", __name__)

BACKUP_DIR = "backups"
os.makedirs(BACKUP_DIR, exist_ok=True)

users = [{"username": "admin", "password": "admin123", "role": "admin"}]

@setting_bp.route("/api/shop_settings", methods=["GET"])
def get_shop_settings():
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM shop_settings WHERE id=1").fetchone()
        if not row:
            conn.execute("INSERT INTO shop_settings (id) VALUES (1)")
            conn.commit()
            row = conn.execute("SELECT * FROM shop_settings WHERE id=1").fetchone()
    return jsonify(dict(row))

@setting_bp.route("/api/shop_settings", methods=["POST"])
def save_shop_settings():
    data = request.json or {}
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO shop_settings (id, shop_name, address, phone, gst_no, footer_note)
            VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                shop_name=excluded.shop_name,
                address=excluded.address,
                phone=excluded.phone,
                gst_no=excluded.gst_no,
                footer_note=excluded.footer_note
        """, (
            data.get('shop_name', '').strip(),
            data.get('address', '').strip(),
            data.get('phone', '').strip(),
            data.get('gst_no', '').strip(),
            data.get('footer_note', '').strip()
        ))
        conn.commit()
    return jsonify({"status": "ok"})

@setting_bp.route("/api/settings/backup", methods=["POST"])
def api_create_backup():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"backup_{timestamp}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    shutil.copy2(MAIN_DB, backup_path)
    return jsonify({"status": "ok", "filename": backup_name})

@setting_bp.route("/api/settings/backups", methods=["GET"])
def api_get_backups():
    backups = []
    for f in os.listdir(BACKUP_DIR):
        if f.endswith('.db'):
            path = os.path.join(BACKUP_DIR, f)
            stat = os.stat(path)
            backups.append({
                "name": f,
                "size": f"{stat.st_size/1024:.1f} KB",
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            })
    return jsonify(sorted(backups, key=lambda x: x["name"], reverse=True))

@setting_bp.route("/api/settings/backup/<filename>", methods=["GET"])
def api_download_backup(filename):
    backup_path = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(backup_path):
        return jsonify({"error": "Not found"}), 404
    return send_file(backup_path, as_attachment=True, download_name=filename)

@setting_bp.route("/api/settings/import", methods=["POST"])
def api_import_backup():
    if 'backup' not in request.files:
        return jsonify({"error": "No file"}), 400
    file = request.files['backup']
    temp_path = os.path.join(BACKUP_DIR, "temp_import.db")
    file.save(temp_path)
    shutil.copy2(temp_path, MAIN_DB)
    os.remove(temp_path)
    return jsonify({"status": "ok"})

@setting_bp.route("/api/export/tables", methods=["GET"])
def api_get_export_tables():
    tables = ["barcodes", "departments", "parties", "vouchers",
              "accounts", "items", "purchase_returns", "sales_returns",
              "purchases", "purchase_items", "sales", "sale_items",
              "purchase_borrow", "sales_borrow"]
    return jsonify(tables)

@setting_bp.route("/api/export/excel", methods=["GET"])
def api_export_excel():
    wb = Workbook()
    ws = wb.active
    ws.title = "Export"
    ws.cell(row=1, column=1, value="Export all data")
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="export.xlsx")

@setting_bp.route("/api/export/csv", methods=["GET"])
def api_export_csv():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Export all data"])
    output.seek(0)
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=export.csv"})

@setting_bp.route("/api/users", methods=["GET"])
def api_get_users():
    return jsonify([{"username": u["username"], "role": u["role"]} for u in users])

@setting_bp.route("/api/users", methods=["POST"])
def api_add_user():
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    if any(u["username"] == username for u in users):
        return jsonify({"error": "User exists"}), 409
    users.append({"username": username, "password": password, "role": "user"})
    return jsonify({"status": "ok"})

@setting_bp.route("/api/users/<username>", methods=["DELETE"])
def api_delete_user(username):
    global users
    if username == "admin":
        return jsonify({"error": "Cannot delete admin"}), 400
    users = [u for u in users if u["username"] != username]
    return jsonify({"status": "ok"})
