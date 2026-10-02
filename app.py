import os
import threading
import time

from flask import Flask, render_template, request, jsonify, session

from core.db import ensure_database_exists
from core.schema import init_schema, populate_defaults, migrate_schema, run_background_startup_tasks
from core.auth import get_or_create_secret_key, is_public_path

from routes.purchases import purchases_bp
from routes.sales import sales_bp
from routes.items import items_bp
from routes.parties import parties_bp
from routes.department import department_bp
from routes.reports import reports_bp
from routes.tally import tally_bp
from routes.dashboard import dashboard_bp
from routes.setting import setting_bp
from routes.legacy import legacy_bp
from routes.auth import auth_bp

app = Flask(__name__)
app.secret_key = get_or_create_secret_key()
# Large SQL backup imports (up to ~20 GB) must not be rejected by Flask
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024 * 1024  # 20 GB

app.register_blueprint(auth_bp)
app.register_blueprint(purchases_bp)
app.register_blueprint(sales_bp)
app.register_blueprint(items_bp)
app.register_blueprint(parties_bp)
app.register_blueprint(department_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(tally_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(setting_bp)
app.register_blueprint(legacy_bp)

# Every /api/* route requires a logged-in session except the auth endpoints
# themselves (login/logout/status/setup). The page shell ("/") and static
# assets are always servable so the login card can render on top of it.
@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.before_request
def require_login():
    if is_public_path(request.path):
        return None
    if request.path.startswith("/api/"):
        if not session.get("user_id"):
            return jsonify({"error": "Authentication required"}), 401
    return None

@app.route("/")
def index():
    return render_template("base.html", v=int(time.time()))


def init_app():
    """Run fast, blocking startup tasks:
      1. Create the PostgreSQL database if it doesn't exist yet.
      2. Run schema.sql + populate defaults on a brand-new DB.
      3. Run idempotent DDL migrations (ALTER TABLE / CREATE INDEX).

    Heavy tasks (cache recompute, Excel import) are NOT run here;
    they are dispatched to a background thread so the server starts
    serving requests immediately after this function returns.
    """
    db_just_created = ensure_database_exists()
    if db_just_created:
        init_schema()
        populate_defaults()
        print("--------------------------New Database Created Successfully!--------------------------")
    migrate_schema()

    # Dispatch slow tasks to a background daemon thread.
    # daemon=True means the thread won't prevent Python from exiting.
    bg = threading.Thread(target=run_background_startup_tasks, daemon=True)
    bg.name = "startup-bg"
    bg.start()
    print("[startup] Server is ready. Background tasks are running in the background.")


if __name__ == "__main__":
    init_app()

    # Bind address / port come from .env (APP_HOST / APP_PORT); defaults = local only.
    APP_HOST = os.environ.get("APP_HOST", "127.0.0.1")
    APP_PORT = int(os.environ.get("APP_PORT", "5000"))

    # Production: use Waitress (pure-Python WSGI server, works on Windows + Linux).
    # Falls back to Flask dev server only if waitress is not installed.
    try:
        from waitress import serve
        print(f"[startup] Starting Waitress production server on http://{APP_HOST}:{APP_PORT}")
        serve(app, host=APP_HOST, port=APP_PORT, threads=8, max_request_body_size=20 * 1024 * 1024 * 1024, channel_timeout=3600)
    except ImportError:
        print(
            "[startup] WARNING: waitress not installed. "
            "Falling back to Flask dev server (NOT suitable for production). "
            "Install with: pip install waitress"
        )
        app.run(debug=False, host=APP_HOST, port=APP_PORT, threaded=True)

