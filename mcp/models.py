"""Read-only mirror of the tables this connector reads.

This service deploys on its own (Railway root directory ``mcp/``) and therefore
cannot import the main app's ``app/models.py``. What lives here is the same
table and column names with none of the write helpers (no
``Profile.get_or_create``), and no ``db.create_all()`` anywhere - this service
never creates or migrates a schema, it only reads the one the main app's
Flask-Migrate migrations own.

If a column or table is ever renamed in the main app, mirror the rename here
and confirm with ``python mcp/check_drift.py``.
"""

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

PRODUCT_STATUSES = ['currently_using', 'wishlist', 'finished', 'abandoned']
SEVERITIES = ['avoid', 'caution', 'good']


class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    brand = db.Column(db.String(200))
    category = db.Column(db.String(100))
    status = db.Column(db.String(30), nullable=False)
    rating = db.Column(db.Integer)          # 1-5
    skin_notes = db.Column(db.Text)
    ingredients = db.Column(db.Text)
    barcode = db.Column(db.String(64))
    photo_url = db.Column(db.String(300))
    date_started = db.Column(db.Date)
    date_finished = db.Column(db.Date)
    created_at = db.Column(db.DateTime)     # naive UTC
    updated_at = db.Column(db.DateTime)     # naive UTC


class Haircut(db.Model):
    __tablename__ = 'haircuts'
    id = db.Column(db.Integer, primary_key=True)
    salon_or_barber = db.Column(db.String(200))
    date = db.Column(db.Date, nullable=False)
    description = db.Column(db.Text)
    how_to_request = db.Column(db.Text)
    rating = db.Column(db.Integer)          # 1-10
    photo_url = db.Column(db.String(300))
    created_at = db.Column(db.DateTime)


class Profile(db.Model):
    """Singleton row; the main app creates it on first visit to the home page."""
    __tablename__ = 'profile'
    id = db.Column(db.Integer, primary_key=True)
    skin_type = db.Column(db.String(200))
    preferred_brands = db.Column(db.Text)
    preferred_ingredients = db.Column(db.Text)
    notes = db.Column(db.Text)
    wake_time = db.Column(db.Time)
    sleep_time = db.Column(db.Time)
    updated_at = db.Column(db.DateTime)


class WatchlistItem(db.Model):
    __tablename__ = 'ingredient_watchlist'
    id = db.Column(db.Integer, primary_key=True)
    ingredient_name = db.Column(db.String(200), nullable=False)
    reason = db.Column(db.Text)
    severity = db.Column(db.String(20), nullable=False)   # avoid / caution / good
