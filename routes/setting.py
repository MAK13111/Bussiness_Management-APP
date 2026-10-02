import os
import io
import shutil
import subprocess
import tempfile
import threading
import time
import json
from collections import deque
from datetime import datetime

from flask import Blueprint, request, jsonify, send_file, session, Response, stream_with_context
import psycopg2

from core.db import get_conn, DATABASE_URL, PG_CONFIG, reset_pool
from core.auth import hash_password
from core import backup as pgbackup

setting_bp = Blueprint("setting", __name__)

BACKUP_DIR = "backups"
os.makedirs(BACKUP_DIR, exist_ok=True)

PREV_DATA_DIR = "Previous_data"
os.makedirs(PREV_DATA_DIR, exist_ok=True)



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

# ---------------------------------------------------------------------------
# Thermal printer (ESC/POS over USB). VID / PID live in thermal_printer_settings.
# ---------------------------------------------------------------------------
_thermal_lock = threading.Lock()  # one print job at a time on the USB device


def _thermal_row(conn):
    row = conn.execute("SELECT * FROM thermal_printer_settings WHERE id=1").fetchone()
    if not row:
        conn.execute("INSERT INTO thermal_printer_settings (id) VALUES (1)")
        conn.commit()
        row = conn.execute("SELECT * FROM thermal_printer_settings WHERE id=1").fetchone()
    return dict(row)


def _thermal_error_message(e):
    low = str(e).lower()
    if isinstance(e, ImportError):
        return "python-escpos / pyusb is not installed. Run: pip install python-escpos pyusb libusb-package"
    if "not found" in low or "unable to open" in low:
        return "Printer not found. Check the USB cable, power, and the VID / PID in Settings."
    if "backend" in low or "access denied" in low or "insufficient permissions" in low or "not supported or implemented" in low:
        return "The app cannot access the printer. Install the WinUSB driver for this printer using Zadig (one-time setup)."
    return "Thermal print failed: " + str(e)


@setting_bp.route("/api/thermal_printer_settings", methods=["GET"])
def get_thermal_printer_settings():
    with get_conn() as conn:
        cfg = _thermal_row(conn)
    return jsonify(cfg)


@setting_bp.route("/api/thermal_printer_settings", methods=["POST"])
def save_thermal_printer_settings():
    from core import thermal_printer as tp
    data = request.json or {}
    vid = str(data.get("vendor_id") or "").strip()
    pid = str(data.get("product_id") or "").strip()
    enabled = 1 if data.get("enabled") else 0
    try:
        if vid or pid or enabled:
            vid = "%04X" % tp.parse_hex_id(vid)
            pid = "%04X" % tp.parse_hex_id(pid)
    except ValueError:
        return jsonify({"status": "error", "message": "VID and PID must be hex values, e.g. 0416 and 5011"}), 400
    paper_width = 58 if int(data.get("paper_width") or 80) == 58 else 80
    auto_cut = 1 if data.get("auto_cut") else 0
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO thermal_printer_settings (id, enabled, vendor_id, product_id, paper_width, auto_cut)
            VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                enabled=excluded.enabled,
                vendor_id=excluded.vendor_id,
                product_id=excluded.product_id,
                paper_width=excluded.paper_width,
                auto_cut=excluded.auto_cut
        """, (enabled, vid, pid, paper_width, auto_cut))
        conn.commit()
    return jsonify({"status": "ok"})


@setting_bp.route("/api/thermal_printer/test", methods=["POST"])
def thermal_printer_test():
    data = request.json or {}
    try:
        from core import thermal_printer as tp
        with get_conn() as conn:
            cfg = _thermal_row(conn)
        # Use the values typed on screen if given, else the saved ones.
        vid = tp.parse_hex_id(data.get("vendor_id") or cfg["vendor_id"])
        pid = tp.parse_hex_id(data.get("product_id") or cfg["product_id"])
        width = 58 if int(data.get("paper_width") or cfg["paper_width"] or 80) == 58 else 80
        cut = bool(data["auto_cut"]) if "auto_cut" in data else bool(cfg["auto_cut"])
        with _thermal_lock:
            tp.print_test_page(vid, pid, width, cut)
    except ValueError:
        return jsonify({"status": "error", "message": "Enter a valid VID and PID first (hex, e.g. 0416 and 5011)"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": _thermal_error_message(e)}), 500
    return jsonify({"status": "ok"})


@setting_bp.route("/api/thermal_printer/print", methods=["POST"])
def thermal_printer_print():
    data = request.json or {}
    try:
        from core import thermal_printer as tp
        with get_conn() as conn:
            cfg = _thermal_row(conn)
            shop_row = conn.execute("SELECT * FROM shop_settings WHERE id=1").fetchone()
        if not cfg["enabled"]:
            return jsonify({"status": "disabled"})
        shop = dict(shop_row) if shop_row else {}
        vid = tp.parse_hex_id(cfg["vendor_id"])
        pid = tp.parse_hex_id(cfg["product_id"])
        with _thermal_lock:
            tp.print_receipt(vid, pid, data, shop, cfg["paper_width"], bool(cfg["auto_cut"]))
    except ValueError:
        return jsonify({"status": "error", "message": "Thermal printer VID / PID is not set correctly in Settings."}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": _thermal_error_message(e)}), 500
    return jsonify({"status": "ok"})


def _pg_env():
    """Env vars for pg_dump/psql subprocesses, mirroring core/db.py's connection
    info. Postgres has no single file to copy like sqlite did, so backups are
    taken with pg_dump instead -- same user-facing feature (create/list/
    download/restore a backup), different mechanism underneath."""
    env = os.environ.copy()
    if not DATABASE_URL:
        if PG_CONFIG.get("password"):
            env["PGPASSWORD"] = PG_CONFIG["password"]
    return env


def _pg_dump_args():
    if DATABASE_URL:
        return [DATABASE_URL]
    return [
        "-h", PG_CONFIG["host"], "-p", str(PG_CONFIG["port"]),
        "-U", PG_CONFIG["user"], "-d", PG_CONFIG["dbname"],
    ]


def _target_db_name():
    """The name of the app's own database, however it's configured."""
    if DATABASE_URL:
        return psycopg2.extensions.parse_dsn(DATABASE_URL)["dbname"]
    return PG_CONFIG["dbname"]


def _recreate_empty_database():
    """
    Drops the app's database if it currently exists (first kicking out any
    other connections to it, since Postgres refuses to drop a database
    that's in use) and creates it fresh and empty under the same name.

    Run right before restoring an import so the outcome is identical no
    matter the starting state: whether the database was deleted or already
    had data in it, afterwards it exists and its only contents are whatever
    the imported file contains.
    """
    target_db = _target_db_name()
    maint_params = psycopg2.extensions.parse_dsn(DATABASE_URL) if DATABASE_URL else dict(PG_CONFIG)
    maint_params["dbname"] = "postgres"

    maint_conn = psycopg2.connect(**maint_params)
    maint_conn.autocommit = True  # DROP/CREATE DATABASE can't run inside a transaction block
    try:
        cur = maint_conn.cursor()
        cur.execute("""
            SELECT pg_terminate_backend(pid) FROM pg_stat_activity
            WHERE datname = %s AND pid <> pg_backend_pid()
        """, (target_db,))
        cur.execute('DROP DATABASE IF EXISTS "{}"'.format(target_db.replace('"', '""')))
        cur.execute('CREATE DATABASE "{}"'.format(target_db.replace('"', '""')))
    finally:
        maint_conn.close()


@setting_bp.route("/api/settings/backup", methods=["POST"])
def api_create_backup():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"backup_{timestamp}.zip"
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    part_path = backup_path + ".part"
    try:
        with open(part_path, "wb") as fh:
            pgbackup.write_backup_zip(fh)
        os.replace(part_path, backup_path)   # only a COMPLETE file gets the final name
    except Exception as e:
        if os.path.exists(part_path):
            os.remove(part_path)
        return jsonify({"error": f"Backup failed: {e}"}), 500
    return jsonify({"status": "ok", "filename": backup_name})

@setting_bp.route("/api/settings/backups", methods=["GET"])
def api_get_backups():
    backups = []
    for f in os.listdir(BACKUP_DIR):
        if f.endswith(('.zip', '.sql')):
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
    file_size = os.path.getsize(backup_path)
    response = send_file(backup_path, as_attachment=True, download_name=filename)
    response.headers['Content-Length'] = str(file_size)
    return response

# ── Import progress state (in-memory, single-user server) ─────────────────
_import_state = {
    "running": False,
    "phase": "",       # 'uploading' | 'safetybak' | 'recreating' | 'restoring' | 'recovering' | 'done' | 'error'
    "message": "",
    "file_size": 0,
    "lines_done": 0,
    "error": None,
    "safety_backup": None,   # filename of the pre-import safety backup
}


@setting_bp.route("/api/settings/import/status", methods=["GET"])
def api_import_status():
    """Poll-able JSON endpoint for frontend to check import progress."""
    return jsonify(dict(_import_state))


def _create_safety_backup():
    """
    Export the current database to Previous_data/ before any destructive
    operation.  Returns the absolute path of the saved file, or raises.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safety_path = os.path.join(PREV_DATA_DIR, f"pre_import_{timestamp}.zip")
    part_path   = safety_path + ".part"
    with open(part_path, "wb") as fh:
        pgbackup.write_backup_zip(fh)
    os.replace(part_path, safety_path)
    return safety_path


def _run_zip_import(temp_path):
    """
    Pure-Python restore of a .zip backup (no psql needed).

    Safety guarantee
    ----------------
    1. The current database is exported to Previous_data/ BEFORE touching
       anything.  If the export itself fails the import is aborted (nothing
       was changed).
    2. restore_backup_zip() runs inside a single Postgres transaction.  If
       the file is corrupt / incomplete the transaction is rolled back
       automatically — the database is left exactly as it was.
    3. The safety backup is kept in Previous_data/ so the user always has
       a one-step rollback even after a successful import.
    """
    # ── Phase: safety backup ─────────────────────────────────────────────
    _import_state.update({
        "phase": "safetybak",
        "message": "Creating safety backup of your current data...",
    })
    try:
        safety_path = _create_safety_backup()
        _import_state["safety_backup"] = os.path.basename(safety_path)
    except Exception as e:
        _import_state.update({
            "phase": "error", "running": False,
            "error": f"Could not create safety backup before import: {e}\n"
                     "Import aborted — your data is untouched.",
        })
        return

    # ── Phase: restore ───────────────────────────────────────────────────
    _import_state.update({
        "phase": "restoring",
        "message": "Data import in progress, please wait...",
        "lines_done": 0,
    })

    def _progress(table, rows_done):
        _import_state["lines_done"] = rows_done
        _import_state["message"] = f"Restoring '{table}'... ({rows_done:,} rows loaded)"

    try:
        pgbackup.restore_backup_zip(temp_path, progress=_progress)
    except Exception as e:
        # The transaction was rolled back inside restore_backup_zip —
        # the database still has all the original data.
        _import_state.update({
            "phase": "error", "running": False,
            "error": (
                f"Restore failed — your original data is completely safe.\n\n"
                f"Error: {e}\n\n"
                f"A safety backup was saved at: Previous_data/{_import_state.get('safety_backup', '')}"
            ),
        })
        return

    # ── Success ──────────────────────────────────────────────────────────
    try:  # drop in-memory caches that were built from the old data
        from routes import reports as _reports
        _reports._monthly_cache.clear()
    except Exception:
        pass
    _import_state.update({
        "phase": "done", "running": False,
        "message": "Import successful! App is restarting...",
    })


def _run_import_in_background(temp_path, file_size):
    """Runs the actual DB restore in a background thread, updating _import_state."""
    global _import_state
    try:
        if pgbackup.is_backup_zip(temp_path):
            _run_zip_import(temp_path)
            return

        # ── Legacy .sql backups (made by older versions) still need psql ────
        #
        # Safety guarantee for the destructive SQL path:
        # 1. Export current DB to Previous_data/ BEFORE dropping anything.
        # 2. Drop + recreate + restore.
        # 3. If psql fails → restore from the safety backup automatically so
        #    the app ends up back in its original state.

        # ── Phase: safety backup ────────────────────────────────────────────
        _import_state.update({
            "phase": "safetybak",
            "message": "Creating safety backup of your current data...",
        })
        try:
            safety_path = _create_safety_backup()
            _import_state["safety_backup"] = os.path.basename(safety_path)
        except Exception as e:
            _import_state.update({
                "phase": "error", "running": False,
                "error": f"Could not create safety backup before import: {e}\n"
                         "Import aborted — your data is untouched.",
            })
            return

        # ── Phase: recreate empty database ──────────────────────────────────
        _import_state.update({"phase": "recreating", "message": "Resetting the old database..."})
        try:
            _recreate_empty_database()
        except Exception as e:
            _import_state.update({"phase": "error", "running": False, "error": f"DB recreate failed: {e}"})
            return

        # The recreate step killed every pooled connection; drop them so the app
        # reconnects cleanly instead of reusing dead sockets.
        reset_pool()

        # ── Phase: psql restore ─────────────────────────────────────────────
        _import_state.update({"phase": "restoring", "message": "Data import in progress, please wait...", "lines_done": 0})
        psql_failed = False
        try:
            proc = subprocess.Popen(
                ["psql", *_pg_dump_args(), "-f", temp_path],
                env=_pg_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            # Read stdout line-by-line to track progress and prevent buffer deadlock.
            # Only the last N lines are kept (for error reporting) so memory usage
            # stays flat no matter how large the restore is.
            recent_lines = deque(maxlen=20)
            lines_done = 0
            for line in proc.stdout:
                recent_lines.append(line)
                lines_done += 1
                _import_state["lines_done"] = lines_done
                _import_state["message"] = f"Restore running... ({lines_done} commands processed)"
            proc.wait()
            if proc.returncode != 0:
                err_text = "".join(recent_lines)  # last up to 20 lines only
                psql_failed = True
                psql_error  = f"psql restore failed:\n{err_text}"
        except FileNotFoundError:
            psql_failed = True
            psql_error  = "psql not found — please install PostgreSQL client tools."

        if psql_failed:
            # ── Auto-recovery: restore from safety backup ───────────────────
            _import_state.update({
                "phase": "recovering",
                "message": "Import failed — restoring your original data from safety backup...",
            })
            try:
                _recreate_empty_database()
                reset_pool()

                def _noop_progress(t, r): pass
                pgbackup.restore_backup_zip(safety_path, progress=_noop_progress)
                reset_pool()
                _import_state.update({
                    "phase": "error", "running": False,
                    "error": (
                        f"{psql_error}\n\n"
                        "✓ Your original data has been fully restored automatically.\n"
                        f"Safety backup kept at: Previous_data/{os.path.basename(safety_path)}"
                    ),
                })
            except Exception as rec_err:
                _import_state.update({
                    "phase": "error", "running": False,
                    "error": (
                        f"{psql_error}\n\n"
                        f"⚠ Auto-recovery also failed: {rec_err}\n"
                        f"Your safety backup is at: Previous_data/{os.path.basename(safety_path)}\n"
                        "Use it to manually restore your data."
                    ),
                })
            return

        _import_state.update({"phase": "done", "running": False, "message": "Import successful! App is restarting..."})

    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


@setting_bp.route("/api/settings/import", methods=["POST"])
def api_import_backup():
    global _import_state

    if _import_state.get("running"):
        return jsonify({"error": "An import is already running. Please wait."}), 409

    if 'backup' not in request.files:
        return jsonify({"error": "No file"}), 400

    file = request.files['backup']
    file_size = request.content_length or 0

    temp_path = os.path.join(BACKUP_DIR, "temp_import.upload")

    # Phase 1 – save uploaded file
    _import_state = {
        "running": True,
        "phase": "uploading",
        "message": "Saving file to server...",
        "file_size": file_size,
        "lines_done": 0,
        "error": None,
    }

    try:
        # Write the upload to a temp file inside BACKUP_DIR first, then
        # rename it to the final path.  Using a NamedTemporaryFile in the
        # same directory as the destination guarantees the final rename is
        # atomic (same filesystem) and avoids any dependency on Werkzeug's
        # internal temp file (which may already be deleted, or may live on a
        # different filesystem / use a Windows short path like PERFEC~1).
        with tempfile.NamedTemporaryFile(
            dir=BACKUP_DIR, delete=False, suffix=".upload.tmp"
        ) as tmp:
            tmp_name = tmp.name
        try:
            file.save(tmp_name)
            os.replace(tmp_name, temp_path)
        except Exception:
            try:
                os.remove(tmp_name)
            except OSError:
                pass
            raise
        saved_size = os.path.getsize(temp_path)
        _import_state["file_size"] = saved_size
        _import_state["message"] = f"File saved ({saved_size / (1024**3):.2f} GB). Starting DB restore..."
    except Exception as e:
        _import_state.update({"phase": "error", "running": False, "error": f"File save failed: {e}"})
        return jsonify({"error": str(e)}), 500

    # Launch background thread for the heavy work
    t = threading.Thread(target=_run_import_in_background, args=(temp_path, file_size), daemon=True)
    t.start()

    return jsonify({"status": "started"})

@setting_bp.route("/api/export/backup", methods=["GET"])
def api_export_backup():
    """Streams a full-database backup (.zip). Pure Python, no pg_dump needed."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{timestamp}.zip"

    # Fail fast with a readable error if the database can't even be reached.
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1")
    except Exception as e:
        return jsonify({"error": f"Cannot connect to the database: {e}"}), 500

    return Response(
        stream_with_context(pgbackup.stream_backup_zip()),
        mimetype="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@setting_bp.route("/api/users", methods=["GET"])
def api_get_users():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT id, user_name AS username, role, is_active, created_at
            FROM manage_user ORDER BY id
        """).fetchall()
    return jsonify([dict(r) for r in rows])

@setting_bp.route("/api/users", methods=["POST"])
def api_add_user():
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    role = (data.get("role") or "user").strip() or "user"
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM manage_user WHERE user_name=?", (username,)).fetchone()
        if existing:
            return jsonify({"error": "A user with this username already exists"}), 409
        conn.execute("""
            INSERT INTO manage_user (user_name, password, role, is_active, created_at, updated_at)
            VALUES (?, ?, ?, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, (username, hash_password(password), role))
    return jsonify({"status": "ok"})

@setting_bp.route("/api/users/<int:user_id>", methods=["PUT"])
def api_update_user(user_id):
    data = request.json or {}
    username = data.get("username", "").strip()
    role = (data.get("role") or "user").strip() or "user"
    if not username:
        return jsonify({"error": "Username required"}), 400
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM manage_user WHERE id=?", (user_id,)).fetchone()
        if not row:
            return jsonify({"error": "User not found"}), 404
        clash = conn.execute(
            "SELECT id FROM manage_user WHERE user_name=? AND id!=?", (username, user_id)
        ).fetchone()
        if clash:
            return jsonify({"error": "Another user already has this username"}), 409
        conn.execute("""
            UPDATE manage_user SET user_name=?, role=?, updated_at=CURRENT_TIMESTAMP WHERE id=?
        """, (username, role, user_id))
    return jsonify({"status": "ok"})

@setting_bp.route("/api/users/<int:user_id>/password", methods=["POST"])
def api_reset_user_password(user_id):
    data = request.json or {}
    password = data.get("password", "")
    if not password or len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM manage_user WHERE id=?", (user_id,)).fetchone()
        if not row:
            return jsonify({"error": "User not found"}), 404
        conn.execute("""
            UPDATE manage_user SET password=?, updated_at=CURRENT_TIMESTAMP WHERE id=?
        """, (hash_password(password), user_id))
    return jsonify({"status": "ok"})

@setting_bp.route("/api/users/<int:user_id>/toggle", methods=["POST"])
def api_toggle_user(user_id):
    with get_conn() as conn:
        row = conn.execute("SELECT is_active FROM manage_user WHERE id=?", (user_id,)).fetchone()
        if not row:
            return jsonify({"error": "User not found"}), 404
        new_status = not row["is_active"]
        if not new_status:
            active_count = conn.execute(
                "SELECT COUNT(*) c FROM manage_user WHERE is_active=TRUE"
            ).fetchone()["c"]
            if active_count <= 1:
                return jsonify({"error": "Cannot deactivate the only active user"}), 400
        conn.execute("""
            UPDATE manage_user SET is_active=?, updated_at=CURRENT_TIMESTAMP WHERE id=?
        """, (new_status, user_id))
    return jsonify({"status": "ok", "is_active": new_status})

@setting_bp.route("/api/users/<int:user_id>", methods=["DELETE"])
def api_delete_user(user_id):
    if session.get("user_id") == user_id:
        return jsonify({"error": "You cannot delete the account you're currently logged in as"}), 400
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM manage_user WHERE id=?", (user_id,)).fetchone()
        if not row:
            return jsonify({"error": "User not found"}), 404
        total = conn.execute("SELECT COUNT(*) c FROM manage_user").fetchone()["c"]
        if total <= 1:
            return jsonify({"error": "Cannot delete the only remaining user"}), 400
        conn.execute("DELETE FROM manage_user WHERE id=?", (user_id,))
    return jsonify({"status": "ok"})