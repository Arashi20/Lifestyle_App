from datetime import datetime, date, timedelta

from app import db


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    brand = db.Column(db.String(200), nullable=True)
    category = db.Column(db.String(100), nullable=True)  # cleanser, moisturizer, serum, SPF, etc.

    # wishlist / currently_using / finished / abandoned
    status = db.Column(db.String(30), nullable=False, default="wishlist")

    rating = db.Column(db.Integer, nullable=True)  # 1-5, nullable until an opinion is formed
    skin_notes = db.Column(db.Text, nullable=True)

    ingredients = db.Column(db.Text, nullable=True)  # raw ingredient list

    barcode = db.Column(db.String(64), nullable=True)
    photo_url = db.Column(db.String(300), nullable=True)

    date_started = db.Column(db.Date, nullable=True)
    date_finished = db.Column(db.Date, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Product {self.brand} - {self.name}>"


class Haircut(db.Model):
    __tablename__ = "haircuts"

    id = db.Column(db.Integer, primary_key=True)
    salon_or_barber = db.Column(db.String(200), nullable=True)
    date = db.Column(db.Date, nullable=False, default=date.today)
    description = db.Column(db.Text, nullable=True)
    how_to_request = db.Column(db.Text, nullable=True)
    rating = db.Column(db.Integer, nullable=True)  # 1-5
    photo_url = db.Column(db.String(300), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Haircut {self.salon_or_barber} - {self.date}>"


class Profile(db.Model):
    """Singleton row holding the user's own info for the landing page."""

    __tablename__ = "profile"

    id = db.Column(db.Integer, primary_key=True)
    skin_type = db.Column(db.String(200), nullable=True)
    preferred_brands = db.Column(db.Text, nullable=True)
    preferred_ingredients = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    wake_time = db.Column(db.Time, nullable=True)
    sleep_time = db.Column(db.Time, nullable=True)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get_or_create(cls):
        profile = cls.query.first()
        if profile is None:
            profile = cls()
            db.session.add(profile)
            db.session.commit()
        return profile

    @property
    def sleep_duration(self):
        """Time from sleep_time to the next occurrence of wake_time.

        Both are stored as bare times-of-day, so bedtime is numerically
        "later" than wake time even though it comes first chronologically —
        roll over to the next day when wake_time isn't already after it.
        """
        if not self.sleep_time or not self.wake_time:
            return None
        today = date.today()
        sleep_dt = datetime.combine(today, self.sleep_time)
        wake_dt = datetime.combine(today, self.wake_time)
        if wake_dt <= sleep_dt:
            wake_dt += timedelta(days=1)
        return wake_dt - sleep_dt

    @property
    def sleep_duration_display(self):
        duration = self.sleep_duration
        if duration is None:
            return None
        hours, minutes = divmod(int(duration.total_seconds() // 60), 60)
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"

    def __repr__(self):
        return f"<Profile {self.skin_type}>"


class WatchlistItem(db.Model):
    __tablename__ = "ingredient_watchlist"

    id = db.Column(db.Integer, primary_key=True)
    ingredient_name = db.Column(db.String(200), nullable=False)
    reason = db.Column(db.Text, nullable=True)

    # avoid / caution / good
    severity = db.Column(db.String(20), nullable=False, default="caution")

    def __repr__(self):
        return f"<WatchlistItem {self.ingredient_name} ({self.severity})>"
