from datetime import datetime

from flask import Blueprint, render_template, request, redirect, flash, url_for

from app import db
from app.models import Haircut, Product, Profile

profile_bp = Blueprint("profile", __name__)


@profile_bp.route("/")
def home():
    profile = Profile.get_or_create()
    favorite_haircuts = (
        Haircut.query.filter(Haircut.rating >= 4).order_by(Haircut.rating.desc(), Haircut.date.desc()).limit(3).all()
    )
    currently_using_count = Product.query.filter_by(status="currently_using").count()
    wishlist_count = Product.query.filter_by(status="wishlist").count()
    return render_template(
        "profile/home.html",
        profile=profile,
        favorite_haircuts=favorite_haircuts,
        currently_using_count=currently_using_count,
        wishlist_count=wishlist_count,
    )


@profile_bp.route("/profile/edit", methods=["GET", "POST"])
def edit_profile():
    profile = Profile.get_or_create()
    if request.method == "POST":
        profile.skin_type = request.form.get("skin_type")
        profile.preferred_brands = request.form.get("preferred_brands")
        profile.preferred_ingredients = request.form.get("preferred_ingredients")
        profile.notes = request.form.get("notes")
        db.session.commit()
        flash("Profile saved.", "success")
        return redirect(url_for("profile.home"))
    return render_template("profile/edit.html", profile=profile)


@profile_bp.route("/profile/sleep", methods=["POST"])
def update_sleep_schedule():
    profile = Profile.get_or_create()
    wake_time = request.form.get("wake_time")
    sleep_time = request.form.get("sleep_time")
    profile.wake_time = datetime.strptime(wake_time, "%H:%M").time() if wake_time else None
    profile.sleep_time = datetime.strptime(sleep_time, "%H:%M").time() if sleep_time else None
    db.session.commit()
    flash("Sleep schedule updated.", "success")
    return redirect(url_for("profile.home"))
