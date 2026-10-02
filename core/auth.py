import os

import core.env  # noqa: F401 -- loads the .env file
from werkzeug.security import generate_password_hash, check_password_hash

# ─── PASSWORD HASHING ──────────────────────────────────────────────────
# Uses Werkzeug's salted hashing (scrypt/pbkdf2 depending on version).
# Plain-text passwords are never stored anywhere.

def hash_password(plain_password):
    return generate_password_hash(plain_password)


def verify_password(plain_password, password_hash):
    if not password_hash:
        return False
    try:
        return check_password_hash(password_hash, plain_password)
    except Exception:
        return False


# ─── SESSION SECRET KEY ────────────────────────────────────────────────
# Persisted to disk so existing logins survive an app restart instead of
# every user being logged out whenever the server process is relaunched.
SECRET_KEY_PATH = os.path.join("DATABASE", "secret.key")


def get_or_create_secret_key():
    # SECRET_KEY in .env / environment wins. Setting it (or changing it) logs everyone out once.
    env_key = os.environ.get("SECRET_KEY", "").strip()
    if env_key:
        return env_key
    os.makedirs(os.path.dirname(SECRET_KEY_PATH), exist_ok=True)
    if os.path.exists(SECRET_KEY_PATH):
        with open(SECRET_KEY_PATH, "r") as f:
            key = f.read().strip()
            if key:
                return key
    key = os.urandom(32).hex()
    with open(SECRET_KEY_PATH, "w") as f:
        f.write(key)
    return key


# ─── ROUTES THAT DON'T REQUIRE A LOGGED-IN SESSION ─────────────────────
# The single-page shell ("/") is always servable so the login card can be
# shown on top of it; static assets are always servable; and the auth
# endpoints themselves obviously can't require you to already be logged in.
PUBLIC_PATHS = {
    "/",
    "/api/auth/status",
    "/api/auth/login",
    "/api/auth/setup",
    "/api/auth/logout",
}


def is_public_path(path):
    if path in PUBLIC_PATHS:
        return True
    if path.startswith("/static/"):
        return True
    return False