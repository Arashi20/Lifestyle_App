import os
from datetime import timedelta

from dotenv import load_dotenv

# python-dotenv only auto-loads .env when going through Flask's own CLI
# (`flask run`, `flask db upgrade`, etc.) — running `python run.py` directly
# bypasses that, so load it explicitly here to cover every entry point.
load_dotenv()


# Production means "not a local sqlite dev run": Railway sets its own
# environment variable, or we're pointed at a real Postgres database.
_raw_db_url = os.environ.get("DATABASE_URL", "sqlite:///local.db")
IS_PRODUCTION = bool(os.environ.get("RAILWAY_ENVIRONMENT")) or _raw_db_url.startswith(
    ("postgres://", "postgresql://")
)


def _secret_key():
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    if IS_PRODUCTION:
        # A hardcoded fallback would let anyone who has read this source forge
        # a logged-in session cookie, so refuse to start instead.
        raise RuntimeError(
            "SECRET_KEY must be set in production. Generate one with: "
            'python -c "import secrets; print(secrets.token_urlsafe(32))"'
        )
    return "dev-secret-change-me"


class Config:
    SECRET_KEY = _secret_key()

    # Railway provides DATABASE_URL for the Postgres addon.
    # Falls back to local sqlite for quick local dev without Postgres running.
    _db_url = _raw_db_url
    # Use the pure-Python pg8000 driver instead of psycopg2 — psycopg2 needs
    # the native libpq.so.5 at runtime, which Nixpacks' build doesn't reliably
    # provide (a GLIBC/library-path mismatch, not just a missing-package
    # issue — adding libpq5 via aptPkgs did not fix it). pg8000 has no native
    # dependencies at all, avoiding the problem entirely.
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql+pg8000://", 1)
    elif _db_url.startswith("postgresql://"):
        _db_url = _db_url.replace("postgresql://", "postgresql+pg8000://", 1)

    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Open Beauty Facts API base (no key required)
    OPEN_BEAUTY_FACTS_API = "https://world.openbeautyfacts.org/api/v2"

    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "app/static/uploads")

    # Only needed locally if the Tesseract binary isn't on PATH (common on
    # Windows). Unset in production — the apt-installed tesseract-ocr on
    # Railway is already on PATH, so pytesseract finds it without this.
    TESSERACT_CMD = os.environ.get("TESSERACT_CMD")

    # Single-user login gate. Set via `flask set-password`, which writes
    # both values to .env — never store a plaintext password here.
    AUTH_USERNAME = os.environ.get("AUTH_USERNAME")
    AUTH_PASSWORD_HASH = os.environ.get("AUTH_PASSWORD_HASH")

    # Sliding inactivity timeout: Flask refreshes the session's expiry on
    # every request by default (SESSION_REFRESH_EACH_REQUEST), so this is
    # "logged out 15 min after your last request," not "15 min after login."
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=15)
    SESSION_REFRESH_EACH_REQUEST = True

    # Session cookie hardening. SameSite=Lax keeps the browser from sending
    # the cookie on cross-site form posts (CSRF); Secure keeps it off plain
    # http once deployed behind Railway's https.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = IS_PRODUCTION

    # Caps request bodies (the OCR photo upload is the only big one), so a
    # huge upload can't exhaust memory.
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
